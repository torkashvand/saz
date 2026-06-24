"""Write repository for OIDC provider configs and external identities."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from saz.db.models import AuthProvider, ExternalIdentity
from saz.repositories.base import BaseRepository


class AuthProviderRepository(BaseRepository[AuthProvider]):
    """Persistence for OIDC provider configurations."""

    def __init__(self, session: Session):
        super().__init__(session, AuthProvider)

    def create(
        self,
        *,
        provider_key: str,
        display_name: str,
        issuer: str,
        client_id: str,
        client_secret_encrypted: bytes | None,
        scopes: str = "openid profile email",
        enabled: bool = False,
        allowed_domains: str | None = None,
        jit_enabled: bool = False,
        default_role: str = "viewer",
    ) -> AuthProvider:
        provider = AuthProvider(
            id=str(uuid4()),
            provider_key=provider_key,
            display_name=display_name,
            issuer=issuer,
            client_id=client_id,
            client_secret_encrypted=client_secret_encrypted,
            scopes=scopes,
            enabled=enabled,
            allowed_domains=allowed_domains,
            jit_enabled=jit_enabled,
            default_role=default_role,
        )
        return self.add(provider)

    def get_by_key(self, provider_key: str) -> AuthProvider | None:
        return self.session.scalar(
            select(AuthProvider).where(AuthProvider.provider_key == provider_key)
        )

    def list_all(self, *, enabled_only: bool = False) -> list[AuthProvider]:
        stmt = select(AuthProvider)
        if enabled_only:
            stmt = stmt.where(AuthProvider.enabled.is_(True))
        stmt = stmt.order_by(AuthProvider.display_name.asc())
        return list(self.session.scalars(stmt).all())


class ExternalIdentityRepository(BaseRepository[ExternalIdentity]):
    """Persistence for IdP-subject → local-user links."""

    def __init__(self, session: Session):
        super().__init__(session, ExternalIdentity)

    def get_by_subject(self, issuer: str, subject: str) -> ExternalIdentity | None:
        return self.session.scalar(
            select(ExternalIdentity).where(
                and_(ExternalIdentity.issuer == issuer, ExternalIdentity.subject == subject)
            )
        )

    def list_for_user(self, user_id: str) -> list[ExternalIdentity]:
        return list(
            self.session.scalars(
                select(ExternalIdentity).where(ExternalIdentity.user_id == user_id)
            ).all()
        )

    def link(
        self,
        *,
        user_id: str,
        provider_key: str,
        issuer: str,
        subject: str,
        email: str | None,
        email_verified: bool,
    ) -> ExternalIdentity:
        identity = ExternalIdentity(
            id=str(uuid4()),
            user_id=user_id,
            provider_key=provider_key,
            issuer=issuer,
            subject=subject,
            email=email,
            email_verified=email_verified,
            last_login_at=datetime.now(UTC),
        )
        return self.add(identity)
