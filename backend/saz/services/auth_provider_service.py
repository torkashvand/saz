"""Admin management of OIDC provider configurations.

CRUD + a discovery "test" that fetches the issuer's well-known document.
The client secret is encrypted at rest and never returned or logged.
"""

import httpx

from saz.api.errors import ConflictError, ValidationError
from saz.audit.admin_audit import admin_audit
from saz.db.models import AuthProvider, User
from saz.db.unit_of_work import UnitOfWork
from saz.security.secret_box import encrypt_secret


class AuthProviderError(Exception):
    """Raised when a provider operation fails a business rule."""


def fetch_discovery_document(issuer: str) -> dict:
    """Fetch and return an OIDC issuer's discovery document.

    Raises ``httpx.HTTPError`` on network/HTTP failures so callers can render
    a useful test result.
    """
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    resp = httpx.get(url, timeout=10.0, follow_redirects=True)
    resp.raise_for_status()
    data: dict = resp.json()
    return data


class AuthProviderService:
    """Service for admin-only OIDC provider management."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    def list_providers(self) -> list[AuthProvider]:
        assert self.uow.auth_providers is not None
        return self.uow.auth_providers.list_all()

    def get_provider(self, provider_id: str) -> AuthProvider | None:
        assert self.uow.auth_providers is not None
        return self.uow.auth_providers.get(provider_id)

    def public_providers(self) -> list[AuthProvider]:
        assert self.uow.auth_providers is not None
        return self.uow.auth_providers.list_all(enabled_only=True)

    def create_provider(
        self,
        actor: User,
        *,
        provider_key: str,
        display_name: str,
        issuer: str,
        client_id: str,
        client_secret: str,
        scopes: str = "openid profile email",
        enabled: bool = False,
        allowed_domains: str | None = None,
        jit_enabled: bool = False,
        default_role: str = "viewer",
    ) -> AuthProvider:
        assert self.uow.auth_providers is not None
        if self.uow.auth_providers.get_by_key(provider_key):
            raise ConflictError(f"provider already exists: {provider_key}")
        provider = self.uow.auth_providers.create(
            provider_key=provider_key,
            display_name=display_name,
            issuer=issuer.rstrip("/"),
            client_id=client_id,
            client_secret_encrypted=encrypt_secret(client_secret),
            scopes=scopes,
            enabled=enabled,
            allowed_domains=allowed_domains,
            jit_enabled=jit_enabled,
            default_role=default_role,
        )
        self.uow.commit()
        admin_audit(
            "auth_provider.created",
            actor_user_id=actor.id,
            actor_username=actor.username,
            changes={"provider_key": provider_key, "issuer": provider.issuer, "enabled": enabled},
        )
        return provider

    def update_provider(self, actor: User, provider_id: str, **fields: object) -> AuthProvider:
        assert self.uow.auth_providers is not None
        provider = self.uow.auth_providers.get(provider_id)
        if provider is None:
            raise AuthProviderError(f"provider not found: {provider_id}")

        changes: dict[str, object] = {}
        # client_secret is re-encrypted, never echoed into the audit log.
        secret = fields.pop("client_secret", None)
        if isinstance(secret, str) and secret:
            provider.client_secret_encrypted = encrypt_secret(secret)
            changes["client_secret"] = "rotated"

        for key in (
            "display_name",
            "issuer",
            "client_id",
            "scopes",
            "enabled",
            "allowed_domains",
            "jit_enabled",
            "default_role",
        ):
            if key in fields and fields[key] is not None:
                value = fields[key]
                if key == "issuer" and isinstance(value, str):
                    value = value.rstrip("/")
                setattr(provider, key, value)
                changes[key] = value

        self.uow.commit()
        admin_audit(
            "auth_provider.updated",
            actor_user_id=actor.id,
            actor_username=actor.username,
            changes={"provider_key": provider.provider_key, **changes},
        )
        return provider

    def delete_provider(self, actor: User, provider_id: str) -> None:
        assert self.uow.auth_providers is not None
        provider = self.uow.auth_providers.get(provider_id)
        if provider is None:
            raise AuthProviderError(f"provider not found: {provider_id}")
        key = provider.provider_key
        self.uow.auth_providers.delete(provider)
        self.uow.commit()
        admin_audit(
            "auth_provider.deleted",
            actor_user_id=actor.id,
            actor_username=actor.username,
            changes={"provider_key": key},
        )

    def test_provider(self, provider_id: str) -> dict:
        """Fetch the issuer discovery document and report endpoints or error."""
        provider = self.get_provider(provider_id)
        if provider is None:
            raise AuthProviderError(f"provider not found: {provider_id}")
        try:
            doc = fetch_discovery_document(provider.issuer)
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "detail": f"discovery failed: {exc}"}
        auth_ep = doc.get("authorization_endpoint")
        token_ep = doc.get("token_endpoint")
        if not auth_ep or not token_ep:
            raise ValidationError("discovery document missing required endpoints")
        return {
            "ok": True,
            "detail": "discovery document fetched",
            "authorization_endpoint": auth_ep,
            "token_endpoint": token_ep,
        }
