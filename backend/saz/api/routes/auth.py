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

from fastapi import APIRouter, HTTPException, Request, Response, status

from saz.api.dependencies import AuthenticatedUserDep, AuthProviderServiceDep, AuthServiceDep
from saz.api.schemas.auth_provider_schemas import PublicProviderResponse
from saz.api.schemas.auth_schemas import (
    ChangePasswordRequest,
    CurrentUserResponse,
    LoginRequest,
    SessionListResponse,
    SessionResponse,
    TokenResponse,
)
from saz.audit.admin_audit import admin_audit
from saz.security import InvalidTokenError, TokenExpiredError, decode_access_token
from saz.services.auth_service import AuthError
from saz.settings import settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = logging.getLogger(__name__)

# The refresh cookie is scoped to the auth routes so it is only sent on
# refresh/logout calls, never on every API request.
_REFRESH_COOKIE_PATH = "/api/v1/auth"


def _user_response(user) -> CurrentUserResponse:  # type: ignore[no-untyped-def]
    return CurrentUserResponse.model_validate(user)


def _set_refresh_cookie(response: Response, secret: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=secret,
        max_age=settings.SESSION_ABSOLUTE_TIMEOUT_DAYS * 24 * 3600,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path=_REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path=_REFRESH_COOKIE_PATH,
    )


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


def _current_session_id(request: Request) -> str | None:
    """Best-effort read of the ``sid`` from the bearer token so the session
    list can flag the caller's own session. Never raises."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    try:
        claims = decode_access_token(auth_header[7:])
    except (InvalidTokenError, TokenExpiredError):
        return None
    sid = claims.get("sid")
    return sid if isinstance(sid, str) else None


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest, request: Request, response: Response, auth: AuthServiceDep
) -> TokenResponse:
    """Exchange a username-or-email + password for a short-lived access token
    plus a server-side refresh session (set as an HttpOnly cookie).

    The token is minted regardless of ``must_change_password``; the backend
    gates operational endpoints separately. The frontend reads that flag from
    the returned user object and redirects accordingly.
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

    ip, user_agent = _client_meta(request)
    token, expires_at, secret, _session = auth.start_session(
        user, auth_method="local", ip=ip, user_agent=user_agent
    )
    auth.uow.commit()
    _set_refresh_cookie(response, secret)
    return TokenResponse(access_token=token, expires_at=expires_at, user=_user_response(user))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response, auth: AuthServiceDep) -> TokenResponse:
    """Rotate the refresh session and mint a new access token.

    Reads the opaque refresh secret from the HttpOnly cookie. On success the
    cookie is replaced with the rotated secret; a replayed (already-rotated)
    secret revokes the session.
    """
    secret = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    try:
        token, expires_at, new_secret, session = auth.refresh_session(secret)
    except AuthError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = auth.uow.users.get(session.user_id)  # type: ignore[union-attr]
    assert user is not None
    _set_refresh_cookie(response, new_secret)
    return TokenResponse(access_token=token, expires_at=expires_at, user=_user_response(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, auth: AuthServiceDep) -> Response:
    """Revoke the current refresh session and clear the cookie. Idempotent."""
    secret = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if secret:
        auth.revoke_session_by_secret(secret)
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout_all")
async def logout_all(user: AuthenticatedUserDep, response: Response, auth: AuthServiceDep) -> dict:
    """Revoke every refresh session for the current user (all devices)."""
    revoked = auth.revoke_all_sessions(user.id)
    _clear_refresh_cookie(response)
    return {"revoked": revoked}


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    user: AuthenticatedUserDep, request: Request, auth: AuthServiceDep
) -> SessionListResponse:
    """List the current user's active refresh sessions."""
    current_sid = _current_session_id(request)
    sessions = auth.list_sessions(user.id)
    items = []
    for s in sessions:
        item = SessionResponse.model_validate(s)
        item.is_current = s.id == current_sid
        items.append(item)
    return SessionListResponse(items=items, total=len(items))


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: str, user: AuthenticatedUserDep, response: Response, auth: AuthServiceDep
) -> Response:
    """Revoke one of the caller's own sessions."""
    if not auth.revoke_session(user.id, session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/providers", response_model=list[PublicProviderResponse])
async def list_public_providers(
    providers: AuthProviderServiceDep,
) -> list[PublicProviderResponse]:
    """Enabled SSO providers for the login screen. Unauthenticated; exposes
    only the key, display name, and the URL that begins the login flow."""
    return [
        PublicProviderResponse(
            provider_key=p.provider_key,
            display_name=p.display_name,
            start_url=f"/api/v1/auth/oidc/{p.provider_key}/start",
        )
        for p in providers.public_providers()
    ]


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
