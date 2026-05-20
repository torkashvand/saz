"""Pydantic schemas for authentication endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    """Payload for POST /api/v1/auth/register."""

    username: str = Field(..., min_length=3, max_length=64)
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=72)
    display_name: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    """Payload for POST /api/v1/auth/login.

    ``identifier`` may be either a username or an email — the API resolves
    both against the same column index so the UI can present a single
    field.
    """

    identifier: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=72)


class TokenResponse(BaseModel):
    """Response shape for both /login and /register (returning a fresh token)."""

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
    created_at: datetime
    last_login_at: datetime | None = None


TokenResponse.model_rebuild()
