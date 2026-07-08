"""Credential management endpoints."""

from fastapi import APIRouter

from saz.api.dependencies import CredentialServiceDep, CurrentUserDep, OperatorUserDep
from saz.api.errors import NotFoundError
from saz.api.schemas.credential_schemas import (
    CreateCredentialRequest,
    CredentialListResponse,
    CredentialResponse,
    UpdateCredentialRequest,
)

router = APIRouter(prefix="/api/v1/credentials", tags=["credentials"])


@router.get("", response_model=CredentialListResponse)
async def list_credentials(
    service: CredentialServiceDep,
    _user: CurrentUserDep,
) -> CredentialListResponse:
    """List all stored credentials (metadata only, no sensitive data)."""
    credentials = service.list()

    return CredentialListResponse(
        items=[
            CredentialResponse(
                name=c.name,
                type=c.type,
                description=c.description,
                created_at=c.created_at.isoformat(),
                updated_at=c.updated_at.isoformat(),
            )
            for c in credentials
        ],
        total=len(credentials),
    )


@router.post("", response_model=CredentialResponse)
async def create_credential(
    req: CreateCredentialRequest,
    service: CredentialServiceDep,
    user: OperatorUserDep,
) -> CredentialResponse:
    """Create a new encrypted credential."""
    credential_name = service.create(
        name=req.name,
        credential_type=req.type,
        data=req.data,
        description=req.description,
        created_by_user_id=user.id,
    )

    # Get the created credential metadata
    credentials = service.list()
    credential = next((c for c in credentials if c.name == credential_name), None)
    if not credential:
        raise NotFoundError(f"Credential not found after creation: {credential_name}")

    return CredentialResponse(
        name=credential.name,
        type=credential.type,
        description=credential.description,
        created_at=credential.created_at.isoformat(),
        updated_at=credential.updated_at.isoformat(),
    )


@router.get("/{name}", response_model=CredentialResponse)
async def get_credential(
    name: str,
    service: CredentialServiceDep,
    _user: CurrentUserDep,
) -> CredentialResponse:
    """Get credential metadata (not the actual sensitive data)."""
    # Get metadata from list
    credentials = service.list()
    credential = next((c for c in credentials if c.name == name), None)
    if not credential:
        raise NotFoundError(f"Credential not found: {name}")

    return CredentialResponse(
        name=credential.name,
        type=credential.type,
        description=credential.description,
        created_at=credential.created_at.isoformat(),
        updated_at=credential.updated_at.isoformat(),
    )


@router.put("/{name}", response_model=CredentialResponse)
async def update_credential(
    name: str,
    req: UpdateCredentialRequest,
    service: CredentialServiceDep,
    _user: OperatorUserDep,
) -> CredentialResponse:
    """Update an existing credential."""
    # data=None means "keep the stored secret" (metadata-only update); the
    # old `req.data or {}` silently WIPED the secret on such updates.
    credential_name = service.update(
        name=name,
        data=req.data,
        description=req.description,
    )

    # Get the updated credential metadata
    credentials = service.list()
    credential = next((c for c in credentials if c.name == credential_name), None)
    if not credential:
        raise NotFoundError(f"Credential not found after update: {credential_name}")

    return CredentialResponse(
        name=credential.name,
        type=credential.type,
        description=credential.description,
        created_at=credential.created_at.isoformat(),
        updated_at=credential.updated_at.isoformat(),
    )


@router.delete("/{name}")
async def delete_credential(
    name: str,
    service: CredentialServiceDep,
    _user: OperatorUserDep,
) -> dict:
    """Delete a credential."""
    service.delete(name)

    return {"status": "deleted", "name": name}
