"""Pydantic schemas for credential management endpoints."""

from pydantic import BaseModel, ConfigDict, Field


class CreateCredentialRequest(BaseModel):
    """Request to create a new credential."""

    name: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$", min_length=1, max_length=255)
    type: str = Field(..., description="Credential type: api_token, ssh_key, password, etc.")
    description: str | None = Field(None, max_length=1000)
    data: dict = Field(..., description="Credential data (will be encrypted)")


class UpdateCredentialRequest(BaseModel):
    """Request to update an existing credential."""

    type: str | None = None
    description: str | None = Field(None, max_length=1000)
    data: dict | None = Field(None, description="New credential data (will be encrypted)")


class CredentialResponse(BaseModel):
    """Response containing credential metadata (never returns actual data)."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    type: str
    description: str | None = None
    created_at: str
    updated_at: str


class CredentialListResponse(BaseModel):
    """Response for listing credentials."""

    credentials: list[CredentialResponse]
    total: int
