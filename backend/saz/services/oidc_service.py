"""OIDC Authorization Code + PKCE login flow.

Two steps:

* ``begin`` builds the IdP authorization URL and a signed transaction token
  (state + nonce + PKCE verifier) the route stashes in a short-lived cookie.
* ``complete`` validates state, exchanges the code for tokens, verifies the
  ID token (signature via JWKS, issuer, audience, nonce), then resolves the
  IdP subject to a local user — linking by verified email or JIT-provisioning
  a viewer when the provider allows it — and opens a refresh session.

The lower-level HTTP/crypto helpers are module-level so tests can substitute
fakes without standing up a real IdP.
"""

import base64
import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from saz.db.models import AuthProvider, User
from saz.db.unit_of_work import UnitOfWork
from saz.domain.literals import Role
from saz.security import hash_password
from saz.services.auth_provider_service import fetch_discovery_document
from saz.services.auth_service import AuthService
from saz.settings import settings

_TX_TYPE = "oidc_tx"
_TX_TTL_SECONDS = 600


class OidcError(Exception):
    """Recoverable OIDC login failure; surfaced to the user as a login error."""


# --- Injectable HTTP/crypto seams (monkeypatched in tests) ---


def exchange_code(
    token_endpoint: str,
    *,
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
    code_verifier: str,
) -> dict:
    """Exchange an authorization code for tokens (client_secret_post + PKCE)."""
    resp = httpx.post(
        token_endpoint,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": code_verifier,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    data: dict = resp.json()
    return data


def verify_id_token(
    id_token: str, *, jwks_uri: str, issuer: str, client_id: str, nonce: str
) -> dict:
    """Verify an ID token's signature and core claims, returning its claims."""
    jwk_client = jwt.PyJWKClient(jwks_uri)
    signing_key = jwk_client.get_signing_key_from_jwt(id_token)
    claims: dict = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience=client_id,
        issuer=issuer,
    )
    if claims.get("nonce") != nonce:
        raise OidcError("ID token nonce mismatch")
    return claims


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class OidcService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow
        self.auth = AuthService(uow)

    def _redirect_uri(self, provider_key: str) -> str:
        base = settings.BACKEND_BASE_URL.rstrip("/")
        return f"{base}/api/v1/auth/oidc/{provider_key}/callback"

    def _provider(self, provider_key: str) -> AuthProvider:
        assert self.uow.auth_providers is not None
        provider = self.uow.auth_providers.get_by_key(provider_key)
        if provider is None or not provider.enabled:
            raise OidcError("unknown or disabled provider")
        return provider

    def begin(self, provider_key: str) -> tuple[str, str]:
        """Return ``(authorization_url, tx_token)`` to start the login."""
        provider = self._provider(provider_key)
        discovery = fetch_discovery_document(provider.issuer)
        authorization_endpoint = discovery.get("authorization_endpoint")
        if not authorization_endpoint:
            raise OidcError("provider discovery missing authorization_endpoint")

        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(48)
        params = {
            "response_type": "code",
            "client_id": provider.client_id,
            "redirect_uri": self._redirect_uri(provider_key),
            "scope": provider.scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
        url = f"{authorization_endpoint}?{urlencode(params)}"
        tx = self._encode_tx(
            {"provider_key": provider_key, "state": state, "nonce": nonce, "verifier": verifier}
        )
        return url, tx

    def complete(
        self,
        provider_key: str,
        *,
        code: str,
        state: str,
        tx_token: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, datetime, str]:
        """Finish login. Returns ``(access_token, expires_at, refresh_secret)``."""
        tx = self._decode_tx(tx_token)
        if tx.get("provider_key") != provider_key or tx.get("state") != state:
            raise OidcError("invalid OIDC state")

        provider = self._provider(provider_key)
        discovery = fetch_discovery_document(provider.issuer)
        token_endpoint = discovery.get("token_endpoint")
        jwks_uri = discovery.get("jwks_uri")
        disc_issuer = discovery.get("issuer", provider.issuer)
        if not token_endpoint or not jwks_uri:
            raise OidcError("provider discovery missing token_endpoint or jwks_uri")

        from saz.security.secret_box import decrypt_secret

        token_resp = exchange_code(
            token_endpoint,
            code=code,
            redirect_uri=self._redirect_uri(provider_key),
            client_id=provider.client_id,
            client_secret=decrypt_secret(provider.client_secret_encrypted),
            code_verifier=str(tx["verifier"]),
        )
        id_token = token_resp.get("id_token")
        if not id_token:
            raise OidcError("token response missing id_token")
        claims = verify_id_token(
            id_token,
            jwks_uri=jwks_uri,
            issuer=disc_issuer,
            client_id=provider.client_id,
            nonce=str(tx["nonce"]),
        )

        user = self._resolve_user(provider, claims)
        token, expires_at, secret, _session = self.auth.start_session(
            user, auth_method="oidc", provider_key=provider_key, ip=ip, user_agent=user_agent
        )
        self.uow.commit()
        return token, expires_at, secret

    # --- Identity resolution ---

    def _resolve_user(self, provider: AuthProvider, claims: dict[str, Any]) -> User:
        assert self.uow.external_identities is not None
        assert self.uow.users is not None
        issuer = str(claims.get("iss"))
        subject = str(claims.get("sub"))
        if not subject or subject == "None":
            raise OidcError("ID token missing subject")

        # 1) Already linked → sign in as that user.
        identity = self.uow.external_identities.get_by_subject(issuer, subject)
        if identity is not None:
            user = self.uow.users.get(identity.user_id)
            if user is None or not user.is_active:
                raise OidcError("the linked account is unavailable")
            identity.last_login_at = datetime.now(UTC)
            return user

        email_raw = claims.get("email")
        email = email_raw.strip().lower() if isinstance(email_raw, str) else None
        verified = bool(claims.get("email_verified"))
        self._check_domain(provider, email)

        # 2) Verified email matches an existing local user → link.
        if email and verified:
            existing = self.uow.users.get_by_email(email)
            if existing is not None:
                self.uow.external_identities.link(
                    user_id=existing.id,
                    provider_key=provider.provider_key,
                    issuer=issuer,
                    subject=subject,
                    email=email,
                    email_verified=verified,
                )
                return existing

        # 3) JIT provisioning (when enabled and email is verified).
        if provider.jit_enabled:
            if not (email and verified):
                raise OidcError("a verified email is required to create an account")
            user = self._jit_create(provider, claims, email)
            self.uow.external_identities.link(
                user_id=user.id,
                provider_key=provider.provider_key,
                issuer=issuer,
                subject=subject,
                email=email,
                email_verified=verified,
            )
            return user

        raise OidcError("no Saz account is linked to this identity")

    def _check_domain(self, provider: AuthProvider, email: str | None) -> None:
        if not provider.allowed_domains:
            return
        allowed = {d.strip().lower() for d in provider.allowed_domains.split(",") if d.strip()}
        domain = email.split("@")[-1] if email and "@" in email else ""
        if domain not in allowed:
            raise OidcError("your email domain is not allowed for this provider")

    def _jit_create(self, provider: AuthProvider, claims: dict[str, Any], email: str) -> User:
        assert self.uow.users is not None
        username = self._unique_username(email)
        display_name = claims.get("name") if isinstance(claims.get("name"), str) else None
        # SSO users authenticate via the IdP; give them an unusable random
        # local password so the local login path can never match.
        user = self.uow.users.create(
            username=username,
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            display_name=display_name,
            role=Role(provider.default_role),
            is_active=True,
            must_change_password=False,
        )
        return user

    def _unique_username(self, email: str) -> str:
        assert self.uow.users is not None
        base = "".join(c for c in email.split("@")[0] if c.isalnum() or c in "_.-")[:48] or "user"
        if len(base) < 3:
            base = f"{base}_sso"
        candidate = base
        suffix = 0
        while self.uow.users.get_by_username(candidate) is not None:
            suffix += 1
            candidate = f"{base}{suffix}"
        return candidate

    # --- Transaction token (state/nonce/verifier) ---

    def _encode_tx(self, data: dict[str, str]) -> str:
        now = datetime.now(UTC)
        payload = {
            **data,
            "type": _TX_TYPE,
            "iat": int(now.timestamp()),
            "exp": int(now.timestamp()) + _TX_TTL_SECONDS,
        }
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    def _decode_tx(self, tx_token: str) -> dict[str, Any]:
        try:
            payload: dict = jwt.decode(
                tx_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
            )
        except jwt.InvalidTokenError as exc:
            raise OidcError("OIDC transaction expired or invalid") from exc
        if payload.get("type") != _TX_TYPE:
            raise OidcError("invalid OIDC transaction")
        return payload
