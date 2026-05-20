"""Authentication endpoints: login, current user, change password.

There is intentionally **no** public registration endpoint and **no**
forgot-password / public reset endpoint. Users are created exclusively
by an admin (via the saz.scripts.create_user CLI for the first admin, or
via the /api/v1/admin/users API thereafter). If a user forgets their
password, an admin resets it from the admin panel; that reset flips
``must_change_password`` so the user must pick a new password on next
login.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from saz.api.dependencies import AuthenticatedUserDep, AuthServiceDep
from saz.api.schemas.auth_schemas import (
    ChangePasswordRequest,
    CurrentUserResponse,
    LoginRequest,
    TokenResponse,
)
from saz.audit.admin_audit import admin_audit
from saz.services.auth_service import AuthError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _user_response(user) -> CurrentUserResponse:  # type: ignore[no-untyped-def]
    return CurrentUserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, auth: AuthServiceDep) -> TokenResponse:
    """Exchange a username-or-email + password for a JWT access token.

    The token is minted regardless of ``must_change_password``; the
    backend gates operational endpoints separately. The frontend reads
    that flag from the returned user object and redirects accordingly.
    """
    try:
        user = auth.authenticate(req.identifier, req.password)
    except AuthError as exc:
        # Use a generic message so we don't leak whether the identifier
        # exists. Account-disabled is the one case worth distinguishing
        # because the user cannot self-recover.
        detail = str(exc) if "disabled" in str(exc) else "invalid credentials"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    token, expires_at = auth.issue_access_token(user)
    return TokenResponse(
        access_token=token,
        expires_at=expires_at,
        user=_user_response(user),
    )


@router.get("/me", response_model=CurrentUserResponse)
async def me(user: AuthenticatedUserDep) -> CurrentUserResponse:
    """Return the currently-authenticated user.

    Uses ``AuthenticatedUserDep`` rather than ``CurrentUserDep`` so users
    with ``must_change_password=True`` can still resolve their session
    (they need to know who they are to render the change-password page).
    """
    return _user_response(user)


@router.post("/change_password", response_model=CurrentUserResponse)
async def change_password(
    req: ChangePasswordRequest,
    user: AuthenticatedUserDep,
    auth: AuthServiceDep,
) -> CurrentUserResponse:
    """Authenticated user changes their own password.

    Requires the current password (so a stolen token alone cannot
    silently rotate the password). On success, clears
    ``must_change_password`` so the user can resume normal use of Saz.
    Emits an audit event attributed to the user.
    """
    try:
        was_forced = user.must_change_password
        updated = auth.change_password(
            user_id=user.id,
            current_password=req.current_password,
            new_password=req.new_password,
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    auth.uow.commit()
    # Audit lives in structured logs (the DB events table is run-scoped).
    # Never include the passwords themselves.
    admin_audit(
        "user.password_changed",
        actor_user_id=updated.id,
        actor_username=updated.username,
        target_user_id=updated.id,
        target_username=updated.username,
        changes={"after_admin_reset": was_forced},
    )
    return _user_response(updated)
