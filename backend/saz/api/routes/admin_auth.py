"""Admin endpoints for OIDC provider configuration (admin-only).

All routes require an authenticated admin. Client secrets are accepted but
never returned.
"""

from fastapi import APIRouter, HTTPException, status

from saz.api.dependencies import AdminUserDep, AuthProviderServiceDep
from saz.api.errors import ConflictError, NotFoundError
from saz.api.schemas.auth_provider_schemas import (
    AuthProviderListResponse,
    AuthProviderResponse,
    CreateAuthProviderRequest,
    ProviderTestResponse,
    UpdateAuthProviderRequest,
)
from saz.services.auth_provider_service import AuthProviderError

router = APIRouter(prefix="/api/v1/admin/auth", tags=["admin-auth"])


def _resp(provider) -> AuthProviderResponse:  # type: ignore[no-untyped-def]
    return AuthProviderResponse.model_validate(provider)


@router.get("/providers", response_model=AuthProviderListResponse)
async def list_providers(
    admin: AdminUserDep, svc: AuthProviderServiceDep
) -> AuthProviderListResponse:
    providers = svc.list_providers()
    return AuthProviderListResponse(items=[_resp(p) for p in providers], total=len(providers))


@router.post("/providers", response_model=AuthProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_provider(
    req: CreateAuthProviderRequest, admin: AdminUserDep, svc: AuthProviderServiceDep
) -> AuthProviderResponse:
    try:
        provider = svc.create_provider(
            actor=admin,
            provider_key=req.provider_key,
            display_name=req.display_name,
            issuer=req.issuer,
            client_id=req.client_id,
            client_secret=req.client_secret,
            scopes=req.scopes,
            enabled=req.enabled,
            allowed_domains=req.allowed_domains,
            redirect_uri=req.redirect_uri,
            jit_enabled=req.jit_enabled,
            default_role=req.default_role,
        )
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _resp(provider)


@router.patch("/providers/{provider_id}", response_model=AuthProviderResponse)
async def update_provider(
    provider_id: str,
    req: UpdateAuthProviderRequest,
    admin: AdminUserDep,
    svc: AuthProviderServiceDep,
) -> AuthProviderResponse:
    try:
        provider = svc.update_provider(admin, provider_id, **req.model_dump(exclude_unset=True))
    except AuthProviderError as exc:
        raise NotFoundError(str(exc)) from exc
    return _resp(provider)


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: str, admin: AdminUserDep, svc: AuthProviderServiceDep
) -> None:
    try:
        svc.delete_provider(admin, provider_id)
    except AuthProviderError as exc:
        raise NotFoundError(str(exc)) from exc


@router.post("/providers/{provider_id}/test", response_model=ProviderTestResponse)
async def test_provider(
    provider_id: str, admin: AdminUserDep, svc: AuthProviderServiceDep
) -> ProviderTestResponse:
    try:
        result = svc.test_provider(provider_id)
    except AuthProviderError as exc:
        raise NotFoundError(str(exc)) from exc
    return ProviderTestResponse(**result)
