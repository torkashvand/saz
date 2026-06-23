"""Auth-session write repository — server-side refresh sessions."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from saz.db.models import AuthSession
from saz.repositories.base import BaseRepository


class AuthSessionRepository(BaseRepository[AuthSession]):
    """Persistence for refresh sessions: create, look up by secret hash,
    list, and revoke. Secrets are only ever stored as hashes."""

    def __init__(self, session: Session):
        super().__init__(session, AuthSession)

    def create(
        self,
        *,
        user_id: str,
        refresh_secret_hash: str,
        idle_expires_at: datetime,
        absolute_expires_at: datetime,
        auth_method: str = "local",
        provider_key: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> AuthSession:
        now = datetime.now(UTC)
        session = AuthSession(
            id=str(uuid4()),
            user_id=user_id,
            refresh_secret_hash=refresh_secret_hash,
            auth_method=auth_method,
            provider_key=provider_key,
            created_at=now,
            last_used_at=now,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
            ip=ip,
            user_agent=user_agent,
        )
        return self.add(session)

    def get_by_refresh_hash(self, refresh_secret_hash: str) -> AuthSession | None:
        stmt = select(AuthSession).where(AuthSession.refresh_secret_hash == refresh_secret_hash)
        return self.session.scalar(stmt)

    def get_by_previous_refresh_hash(self, refresh_secret_hash: str) -> AuthSession | None:
        """Look up by the *prior* secret — a hit means a rotated secret was
        replayed, which we treat as theft."""
        stmt = select(AuthSession).where(
            AuthSession.previous_refresh_secret_hash == refresh_secret_hash
        )
        return self.session.scalar(stmt)

    def list_for_user(self, user_id: str, *, include_revoked: bool = False) -> list[AuthSession]:
        stmt = select(AuthSession).where(AuthSession.user_id == user_id)
        if not include_revoked:
            stmt = stmt.where(AuthSession.revoked_at.is_(None))
        stmt = stmt.order_by(AuthSession.last_used_at.desc())
        return list(self.session.scalars(stmt).all())

    def revoke(self, session: AuthSession, reason: str) -> None:
        if session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)
            session.revoked_reason = reason

    def revoke_all_for_user(self, user_id: str, reason: str) -> int:
        sessions = self.list_for_user(user_id)
        for s in sessions:
            self.revoke(s, reason)
        return len(sessions)
