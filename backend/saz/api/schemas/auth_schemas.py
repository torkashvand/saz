"""Pydantic schemas for authentication endpoints.

Note: there is intentionally no ``RegisterRequest`` schema. Users are
created exclusively by admins (CLI for the first admin, then via the
admin user-management API).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from saz.domain.literals import Role


class LoginRequest(BaseModel):
    """Payload for POST /api/v1/auth/login.

    ``identifier`` may be either a username or an email — the API resolves
    both against the same column index so the UI can present a single
    field.
    """

    identifier: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=72)


class ChangePasswordRequest(BaseModel):
    """Payload for POST /api/v1/auth/change_password.

    ``current_password`` is required even when the user is in the
    ``must_change_password`` state — a stolen token alone must not be
    enough to rotate the password. After an admin reset the "current"
    password is the temporary value the admin handed the user.
    """

    current_password: str = Field(..., min_length=1, max_length=72)
    new_password: str = Field(..., min_length=8, max_length=72)


class TokenResponse(BaseModel):
    """Response shape for /login (returning a fresh token + user info)."""

    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: "CurrentUserResponse"


class CurrentUserResponse(BaseModel):
    """Response for GET /api/v1/auth/me. Never includes password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: str
    display_name: str | None = None
    is_active: bool
    role: Role
    must_change_password: bool
    created_at: datetime
    last_login_at: datetime | None = None


TokenResponse.model_rebuild()
