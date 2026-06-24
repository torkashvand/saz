"""Pydantic schemas for admin user-management endpoints.

These are admin-only — they intentionally expose ``role`` and
``must_change_password`` so the admin UI can render and edit the right
state. Password hashes are never exposed.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from saz.domain.literals import Role


class AdminUserResponse(BaseModel):
    """Admin view of a user. Never includes password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: str
    display_name: str | None = None
    is_active: bool
    role: Role
    must_change_password: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None


class AdminUserListResponse(BaseModel):
    items: list[AdminUserResponse]
    total: int


class AdminCreateUserRequest(BaseModel):
    """Payload for POST /api/v1/admin/users."""

    username: str = Field(..., min_length=3, max_length=64)
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=72)
    display_name: str | None = Field(default=None, max_length=255)
    role: Role = Role.OPERATOR
    is_active: bool = True
    # Default True so admin-minted accounts force the recipient to pick a
    # password the admin doesn't know after first login. Admin can override
    # if creating themselves a service-style account.
    must_change_password: bool = True


class AdminUpdateUserRequest(BaseModel):
    """Payload for PATCH /api/v1/admin/users/{id}.

    Profile fields (username, email, display name). ``is_active`` /
    ``role`` / password rotation each have their own dedicated
    endpoint so the audit trail is unambiguous per operation.
    """

    username: str | None = Field(default=None, min_length=3, max_length=64)
    email: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)


class AdminResetPasswordRequest(BaseModel):
    """Payload for POST /api/v1/admin/users/{id}/reset_password."""

    temporary_password: str = Field(..., min_length=8, max_length=72)


class AdminSetActiveRequest(BaseModel):
    is_active: bool


class AdminSetRoleRequest(BaseModel):
    role: Role


class AdminSessionResponse(BaseModel):
    """Admin view of one of a user's refresh sessions. No secrets."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    auth_method: str
    provider_key: str | None = None
    created_at: datetime
    last_used_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    ip: str | None = None
    user_agent: str | None = None
    # True when this is the session the requesting admin is currently using.
    is_current: bool = False


class AdminSessionListResponse(BaseModel):
    items: list[AdminSessionResponse]
    total: int
