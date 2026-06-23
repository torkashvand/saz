"""Authentication service - create users, login, resolve users from tokens,
change passwords.

This is identity-only. Authorization decisions (role / is_active /
must_change_password gating) live in the FastAPI dependency layer.
"""

import re
from datetime import datetime

from saz.api.errors import ConflictError, ValidationError
from saz.db.models import User
from saz.db.unit_of_work import UnitOfWork
from saz.domain.literals import Role
from saz.security import (
    InvalidTokenError,
    TokenExpiredError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class AuthError(Exception):
    """Generic authentication failure surfaced to the caller as HTTP 401/400."""


_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD_LENGTH = 8


class AuthService:
    """Identity service: who is this user, can they log in.

    Does not decide *what* they can do — a user's ``role`` is persisted
    here, but authorization enforcement lives in the FastAPI dependency
    layer.
    """

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    # --- Validation helpers ---

    @staticmethod
    def _validate_username(username: str) -> str:
        username = username.strip()
        if not _USERNAME_RE.match(username):
            raise ValidationError("username must be 3-64 chars: letters, digits, '_', '.', or '-'")
        return username

    @staticmethod
    def _validate_email(email: str) -> str:
        email = email.strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValidationError("email must be a valid address")
        if len(email) > 255:
            raise ValidationError("email too long")
        return email

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < _MIN_PASSWORD_LENGTH:
            raise ValidationError(f"password must be at least {_MIN_PASSWORD_LENGTH} characters")

    # --- User creation ---

    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        display_name: str | None = None,
        role: Role = Role.OPERATOR,
        is_active: bool = True,
        must_change_password: bool = False,
    ) -> User:
        """Create a new user account. Used by the CLI bootstrap and by the
        admin user-management API. There is no public-facing wrapper —
        callers must be either the CLI (running locally with DB access)
        or an authenticated admin."""
        assert self.uow.users is not None
        username = self._validate_username(username)
        email = self._validate_email(email)
        self._validate_password(password)

        if self.uow.users.get_by_username(username):
            raise ConflictError(f"username already taken: {username}")
        if self.uow.users.get_by_email(email):
            raise ConflictError(f"email already registered: {email}")

        user = self.uow.users.create(
            username=username,
            email=email,
            password_hash=hash_password(password),
            display_name=display_name.strip() if display_name else None,
            is_active=is_active,
            role=role,
            must_change_password=must_change_password,
        )
        self.uow.commit()
        return user

    # --- Login ---

    def authenticate(self, identifier: str, password: str) -> User:
        """Verify credentials and stamp last_login_at.

        ``identifier`` may be either a username or an email — the UI does
        not need separate fields. Returns the user on success; raises
        ``AuthError`` on any failure (wrong identifier, wrong password,
        disabled account). The error message is intentionally generic so
        responses do not leak which half of the credential pair was wrong.
        """
        assert self.uow.users is not None
        if not identifier or not password:
            raise AuthError("invalid credentials")

        user = self.uow.users.get_by_username_or_email(identifier.strip())
        if user is None:
            # Verify against a dummy hash to keep timing roughly constant
            # regardless of whether the identifier exists.
            verify_password(password, "$2b$12$" + "x" * 53)
            raise AuthError("invalid credentials")

        if not verify_password(password, user.password_hash):
            raise AuthError("invalid credentials")

        if not user.is_active:
            raise AuthError("account is disabled")

        self.uow.users.record_login(user.id)
        self.uow.commit()
        return user

    def issue_access_token(self, user: User) -> tuple[str, datetime]:
        """Mint a JWT for ``user``. Returns (token, expires_at)."""
        return create_access_token(user_id=user.id, username=user.username)

    # --- Token → user ---

    def user_from_token(self, token: str) -> User:
        """Resolve a bearer token to the live ``User`` row.

        Raises ``AuthError`` on expired/malformed tokens or if the
        referenced user has been deleted or disabled — never returns a
        stale identity. Note: this *does not* check
        ``must_change_password`` — that gate lives in the FastAPI
        dependency layer so /auth/me and /auth/change_password remain
        reachable for users in the forced-change state.
        """
        assert self.uow.users is not None
        try:
            claims = decode_access_token(token)
        except TokenExpiredError as exc:
            raise AuthError("token has expired") from exc
        except InvalidTokenError as exc:
            raise AuthError("invalid token") from exc

        user_id = claims.get("sub")
        if not isinstance(user_id, str):
            raise AuthError("invalid token")

        user = self.uow.users.get(user_id)
        if user is None:
            raise AuthError("user no longer exists")
        if not user.is_active:
            raise AuthError("account is disabled")
        return user

    # --- Password change (self-service) ---

    def change_password(
        self,
        user_id: str,
        current_password: str,
        new_password: str,
    ) -> User:
        """Authenticated user changes their own password.

        Requires the current password so a stolen token alone cannot
        rotate the password. Clears ``must_change_password`` on success.
        Does not commit — the route layer is responsible for committing
        so audit events flush in the same transaction.
        """
        assert self.uow.users is not None
        user = self.uow.users.get(user_id)
        if user is None:
            raise AuthError("user no longer exists")
        if not user.is_active:
            raise AuthError("account is disabled")

        if not verify_password(current_password, user.password_hash):
            raise AuthError("current password is incorrect")

        self._validate_password(new_password)
        if verify_password(new_password, user.password_hash):
            # Reject reusing the same password — prevents the trivial
            # "change to the same value" workaround for an admin reset.
            raise AuthError("new password must differ from the current one")

        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        return user
