"""Shared cookie helpers for the auth and OIDC routers.

The refresh cookie is HttpOnly, scoped to the auth routes (so it is only
sent on refresh/logout/OIDC calls), and hardened per settings.
"""

from fastapi import Response

from saz.settings import settings

REFRESH_COOKIE_PATH = "/api/v1/auth"


def set_refresh_cookie(response: Response, secret: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=secret,
        max_age=settings.SESSION_ABSOLUTE_TIMEOUT_DAYS * 24 * 3600,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path=REFRESH_COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path=REFRESH_COOKIE_PATH,
    )
