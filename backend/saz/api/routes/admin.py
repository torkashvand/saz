"""Admin user-management endpoints (admin-only).

All routes require an authenticated admin (``AdminUserDep``); the
dependency layer turns away non-admins with 403 before any handler
runs. There is no public registration endpoint and no public
password-reset endpoint — this is the only programmatic way to create
or modify users after the CLI-bootstrapped first admin.
"""

import logging

from fastapi import APIRouter, HTTPException, Query, status

from saz.api.dependencies import AdminServiceDep, AdminUserDep
from saz.api.errors import NotFoundError
from saz.api.schemas.admin_schemas import (
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    AdminSessionListResponse,
    AdminSessionResponse,
    AdminSetActiveRequest,
    AdminSetRoleRequest,
    AdminUpdateUserRequest,
    AdminUserListResponse,
    AdminUserResponse,
)
from saz.services.admin_service import AdminError

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
logger = logging.getLogger(__name__)


def _resp(user) -> AdminUserResponse:  # type: ignore[no-untyped-def]
    return AdminUserResponse.model_validate(user)


def _handle_admin_error(exc: AdminError) -> HTTPException:
    """Translate an AdminError into a 400 with the operator-safe message."""
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    admin: AdminUserDep,
    svc: AdminServiceDep,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> AdminUserListResponse:
    users, total = svc.list_users(limit=limit, offset=offset)
    return AdminUserListResponse(items=[_resp(u) for u in users], total=total)


@router.post("/users", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    req: AdminCreateUserRequest,
    admin: AdminUserDep,
    svc: AdminServiceDep,
) -> AdminUserResponse:
    user = svc.create_user(
        actor=admin,
        username=req.username,
        email=req.email,
        password=req.password,
        display_name=req.display_name,
        role=req.role,
        is_active=req.is_active,
        must_change_password=req.must_change_password,
    )
    return _resp(user)


@router.get("/users/{user_id}", response_model=AdminUserResponse)
async def get_user(
    user_id: str,
    admin: AdminUserDep,
    svc: AdminServiceDep,
) -> AdminUserResponse:
    user = svc.get_user(user_id)
    if user is None:
        raise NotFoundError(f"user not found: {user_id}")
    return _resp(user)


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: str,
    req: AdminUpdateUserRequest,
    admin: AdminUserDep,
    svc: AdminServiceDep,
) -> AdminUserResponse:
    try:
        user = svc.update_profile(
            actor=admin,
            user_id=user_id,
            username=req.username,
            email=req.email,
            display_name=req.display_name,
        )
    except AdminError as exc:
        raise _handle_admin_error(exc) from exc
    return _resp(user)


@router.post("/users/{user_id}/set_active", response_model=AdminUserResponse)
async def set_active(
    user_id: str,
    req: AdminSetActiveRequest,
    admin: AdminUserDep,
    svc: AdminServiceDep,
) -> AdminUserResponse:
    try:
        user = svc.set_active(actor=admin, user_id=user_id, is_active=req.is_active)
    except AdminError as exc:
        raise _handle_admin_error(exc) from exc
    return _resp(user)


@router.post("/users/{user_id}/set_role", response_model=AdminUserResponse)
async def set_role(
    user_id: str,
    req: AdminSetRoleRequest,
    admin: AdminUserDep,
    svc: AdminServiceDep,
) -> AdminUserResponse:
    try:
        user = svc.set_role(actor=admin, user_id=user_id, role=req.role)
    except AdminError as exc:
        raise _handle_admin_error(exc) from exc
    return _resp(user)


@router.post("/users/{user_id}/reset_password", response_model=AdminUserResponse)
async def reset_password(
    user_id: str,
    req: AdminResetPasswordRequest,
    admin: AdminUserDep,
    svc: AdminServiceDep,
) -> AdminUserResponse:
    """Admin resets a user's password. The user is then required to
    change it on next login. The temporary password is never returned
    in the response; the admin is responsible for handing it to the user
    out-of-band.
    """
    try:
        user = svc.reset_password(
            actor=admin,
            user_id=user_id,
            temporary_password=req.temporary_password,
        )
    except AdminError as exc:
        raise _handle_admin_error(exc) from exc
    return _resp(user)


@router.get("/users/{user_id}/sessions", response_model=AdminSessionListResponse)
async def list_user_sessions(
    user_id: str,
    admin: AdminUserDep,
    svc: AdminServiceDep,
) -> AdminSessionListResponse:
    """List a user's active refresh sessions (device, IP, last used)."""
    try:
        sessions = svc.list_user_sessions(user_id)
    except AdminError as exc:
        raise NotFoundError(str(exc)) from exc
    return AdminSessionListResponse(
        items=[AdminSessionResponse.model_validate(s) for s in sessions],
        total=len(sessions),
    )


@router.delete("/users/{user_id}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_user_session(
    user_id: str,
    session_id: str,
    admin: AdminUserDep,
    svc: AdminServiceDep,
) -> None:
    """Revoke a single session belonging to the user."""
    try:
        svc.revoke_user_session(actor=admin, user_id=user_id, session_id=session_id)
    except AdminError as exc:
        raise NotFoundError(str(exc)) from exc


@router.delete("/users/{user_id}/sessions")
async def revoke_all_user_sessions(
    user_id: str,
    admin: AdminUserDep,
    svc: AdminServiceDep,
) -> dict:
    """Revoke every active session for the user (sign them out everywhere)."""
    try:
        revoked = svc.revoke_all_user_sessions(actor=admin, user_id=user_id)
    except AdminError as exc:
        raise NotFoundError(str(exc)) from exc
    return {"revoked": revoked}
