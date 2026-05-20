"""Authentication endpoints: register, login, current user."""

import logging

from fastapi import APIRouter, HTTPException, status

from saz.api.dependencies import AuthServiceDep, CurrentUserDep
from saz.api.schemas.auth_schemas import (
    CurrentUserResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)
from saz.services.auth_service import AuthError
from saz.settings import settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _user_response(user) -> CurrentUserResponse:  # type: ignore[no-untyped-def]
    return CurrentUserResponse.model_validate(user)


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, auth: AuthServiceDep) -> TokenResponse:
    """Create a new user account and return a fresh access token.

    This endpoint is open while RBAC and invitation flows are out of scope.
    Set ALLOW_USER_REGISTRATION=false to disable it once a richer admin
    surface exists.
    """
    if not settings.ALLOW_USER_REGISTRATION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user registration is disabled on this deployment",
        )
    user = auth.register_user(
        username=req.username,
        email=req.email,
        password=req.password,
        display_name=req.display_name,
    )
    token, expires_at = auth.issue_access_token(user)
    return TokenResponse(
        access_token=token,
        expires_at=expires_at,
        user=_user_response(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, auth: AuthServiceDep) -> TokenResponse:
    """Exchange a username-or-email + password for a JWT access token."""
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
async def me(user: CurrentUserDep) -> CurrentUserResponse:
    """Return the currently-authenticated user."""
    return _user_response(user)
