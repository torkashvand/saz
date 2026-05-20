"""User write repository."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from saz.db.models import User
from saz.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Write repository for User aggregate.

    Identity-only: stores who exists and lets callers update login state.
    Authorization concerns (roles, scopes, tenant membership) live elsewhere
    when they exist.
    """

    def __init__(self, session: Session):
        super().__init__(session, User)

    def create(
        self,
        username: str,
        email: str,
        password_hash: str,
        display_name: str | None = None,
        is_active: bool = True,
        is_admin: bool = False,
        must_change_password: bool = False,
    ) -> User:
        """Insert a new user. Caller is responsible for hashing the password."""
        now = datetime.now(UTC)
        user = User(
            id=str(uuid4()),
            username=username,
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            is_active=is_active,
            is_admin=is_admin,
            must_change_password=must_change_password,
            created_at=now,
            updated_at=now,
        )
        return self.add(user)

    def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        return self.session.scalar(stmt)

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        return self.session.scalar(stmt)

    def get_by_username_or_email(self, identifier: str) -> User | None:
        """Resolve a login identifier that may be either a username or email."""
        stmt = select(User).where(or_(User.username == identifier, User.email == identifier))
        return self.session.scalar(stmt)

    def record_login(self, user_id: str) -> User | None:
        """Stamp ``last_login_at`` after a successful authentication."""
        user = self.get(user_id)
        if user:
            user.last_login_at = datetime.now(UTC)
        return user

    def set_active(self, user_id: str, is_active: bool) -> User | None:
        user = self.get(user_id)
        if user:
            user.is_active = is_active
        return user

    def list_all(self, limit: int = 200, offset: int = 0) -> tuple[list[User], int]:
        """Return users ordered by creation time, plus the total count.

        Used by the admin panel — keep it simple, no filtering yet.
        """
        from sqlalchemy import func

        total = self.session.scalar(select(func.count()).select_from(User)) or 0
        stmt = select(User).order_by(User.created_at.asc()).limit(limit).offset(offset)
        return list(self.session.scalars(stmt).all()), int(total)

    def count_active_admins(self) -> int:
        """Used to refuse the last-admin disable/demote."""
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(User)
            .where(User.is_admin.is_(True), User.is_active.is_(True))
        )
        return int(self.session.scalar(stmt) or 0)
