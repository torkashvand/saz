"""Schemas for OIDC provider administration and the public login list.

The client secret is write-only: accepted on create/update, never returned.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# JIT provisioning must never mint an admin; restrict the configurable default
# tier to the two non-privileged roles.
JitRole = Literal["viewer", "operator"]


class AuthProviderResponse(BaseModel):
    """Admin view of a provider. Never includes the client secret."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    provider_key: str
    display_name: str
    issuer: str
    client_id: str
    scopes: str
    enabled: bool
    allowed_domains: str | None = None
    jit_enabled: bool
    default_role: str
    created_at: datetime
    updated_at: datetime


class AuthProviderListResponse(BaseModel):
    items: list[AuthProviderResponse]
    total: int


class CreateAuthProviderRequest(BaseModel):
    provider_key: str = Field(..., pattern=r"^[a-z0-9_-]+$", min_length=2, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=255)
    issuer: str = Field(..., min_length=8, max_length=512)
    client_id: str = Field(..., min_length=1, max_length=512)
    # Optional: public (PKCE-only) clients have no secret. Empty/None stores no secret.
    client_secret: str | None = Field(default=None, max_length=2048)
    scopes: str = Field(default="openid profile email", max_length=512)
    enabled: bool = False
    allowed_domains: str | None = Field(default=None, max_length=1024)
    jit_enabled: bool = False
    default_role: JitRole = "viewer"


class UpdateAuthProviderRequest(BaseModel):
    """All fields optional. Omitting ``client_secret`` keeps the stored one."""

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    issuer: str | None = Field(default=None, min_length=8, max_length=512)
    client_id: str | None = Field(default=None, min_length=1, max_length=512)
    client_secret: str | None = Field(default=None, min_length=1, max_length=2048)
    scopes: str | None = Field(default=None, max_length=512)
    enabled: bool | None = None
    allowed_domains: str | None = Field(default=None, max_length=1024)
    jit_enabled: bool | None = None
    default_role: JitRole | None = None


class ProviderTestResponse(BaseModel):
    ok: bool
    detail: str
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None


class PublicProviderResponse(BaseModel):
    """What the unauthenticated login page needs to render an SSO button."""

    provider_key: str
    display_name: str
    start_url: str
