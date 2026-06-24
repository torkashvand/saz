"""OIDC SSO browser endpoints: start the flow and handle the callback.

The browser navigates to ``/start`` (full-page redirect to the IdP), the IdP
redirects back to ``/callback``. On success a refresh session is opened (the
HttpOnly cookie is set) and the browser is sent to the frontend, which then
calls ``/auth/refresh`` to obtain an access token.
"""

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from saz.api.cookies import set_refresh_cookie
from saz.api.dependencies import OidcServiceDep
from saz.services.oidc_service import OidcError
from saz.settings import settings

router = APIRouter(prefix="/api/v1/auth/oidc", tags=["auth-oidc"])
logger = logging.getLogger(__name__)

_TX_COOKIE = "saz_oidc_tx"
_TX_COOKIE_PATH = "/api/v1/auth/oidc"


def _frontend_login(params: dict[str, str]) -> str:
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/login?{urlencode(params)}"


@router.get("/{provider_key}/start")
async def oidc_start(provider_key: str, oidc: OidcServiceDep) -> Response:
    """Begin the Authorization Code + PKCE flow by redirecting to the IdP."""
    try:
        url, tx = oidc.begin(provider_key)
    except OidcError as exc:
        return RedirectResponse(
            _frontend_login({"sso": "error", "reason": str(exc)}), status_code=303
        )
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(
        key=_TX_COOKIE,
        value=tx,
        max_age=600,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path=_TX_COOKIE_PATH,
    )
    return response


@router.get("/callback")
async def oidc_callback(
    request: Request,
    oidc: OidcServiceDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    """Handle the IdP redirect: validate, open a session, return to the app.

    The provider is recovered from the signed transaction cookie, so the
    redirect URI registered with the IdP does not need the provider in its path
    (and may even live on a different origin that forwards here).
    """
    if error:
        return _redirect_error(error)
    tx = request.cookies.get(_TX_COOKIE)
    if not code or not state or not tx:
        return _redirect_error("missing OIDC callback parameters")

    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    try:
        provider_key = oidc.provider_key_from_tx(tx)
        _token, _expires, secret = oidc.complete(
            provider_key, code=code, state=state, tx_token=tx, ip=ip, user_agent=user_agent
        )
    except OidcError as exc:
        return _redirect_error(str(exc))

    response = RedirectResponse(_frontend_login({"sso": "ok"}), status_code=303)
    set_refresh_cookie(response, secret)
    response.delete_cookie(_TX_COOKIE, path=_TX_COOKIE_PATH)
    return response


def _redirect_error(reason: str) -> RedirectResponse:
    response = RedirectResponse(
        _frontend_login({"sso": "error", "reason": reason}), status_code=303
    )
    response.delete_cookie(_TX_COOKIE, path=_TX_COOKIE_PATH)
    return response
