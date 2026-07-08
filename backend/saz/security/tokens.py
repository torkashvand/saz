"""JWT access-token encoding/decoding.

This is intentionally minimal: HS256 with an expiry claim and the user id
in ``sub``. Refresh tokens, server-side revocation, and audience/issuer
checks are out of scope until a richer identity story (sessions, RBAC,
multi-tenancy) lands.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from saz.settings import settings


class TokenError(Exception):
    """Base class for token errors."""


class TokenExpiredError(TokenError):
    """Raised when a token has passed its ``exp`` claim."""


class InvalidTokenError(TokenError):
    """Raised when a token is malformed, has a bad signature, or is missing
    required claims."""


# Backwards-friendly alias for callers that catch a generic "decode" error.
TokenDecodeError = InvalidTokenError


def _require_secret() -> str:
    secret = settings.JWT_SECRET_KEY
    if not secret:
        # Fail closed: unconfigured deployments do not mint or accept tokens.
        raise InvalidTokenError(
            "JWT_SECRET_KEY is not configured; set a strong random value before "
            "issuing or validating tokens."
        )
    return secret


def create_access_token(
    user_id: str,
    username: str,
    expires_delta: timedelta | None = None,
    session_id: str | None = None,
) -> tuple[str, datetime]:
    """Mint a signed JWT for ``user_id``.

    ``session_id`` binds the token to a refresh session via the ``sid``
    claim; the dependency layer rejects the token once that session is
    revoked. Tokens minted without a session (e.g. test helpers) carry no
    ``sid`` and skip the session check.

    Returns ``(token, expires_at)`` so callers can include the expiry in the
    response without having to decode the token again.
    """
    secret = _require_secret()
    now = datetime.now(UTC)
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    expires_at = now + expires_delta

    claims: dict[str, Any] = {
        "sub": user_id,
        "username": username,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "type": "access",
    }
    if session_id is not None:
        claims["sid"] = session_id
    token = jwt.encode(claims, secret, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    """Validate a JWT and return its claims dict.

    Raises:
        TokenExpiredError: token's ``exp`` is in the past.
        InvalidTokenError: signature mismatch, malformed payload, or missing
            required claims.
    """
    secret = _require_secret()
    try:
        claims = jwt.decode(token, secret, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError(f"invalid token: {exc}") from exc

    if not isinstance(claims, dict):
        raise InvalidTokenError("token payload is not a JSON object")
    if claims.get("type") != "access":
        raise InvalidTokenError("token is not an access token")
    if "sub" not in claims:
        raise InvalidTokenError("token missing 'sub' claim")
    return dict(claims)


# Browsers cannot set Authorization headers on a WebSocket upgrade, so the
# stream endpoint authenticates via a query parameter. Query strings end up in
# proxy/server logs, so instead of the long-lived access token the client
# exchanges it (over the authed HTTP channel) for a short-lived ticket scoped
# to ONE run. A leaked ticket is useless within a minute and never grants
# anything beyond that run's event stream.
STREAM_TICKET_TTL_SECONDS = 60


def create_stream_ticket(user_id: str, run_id: str) -> str:
    """Mint a short-lived ticket authorizing a WS stream for one run."""
    secret = _require_secret()
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": user_id,
        "run_id": run_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=STREAM_TICKET_TTL_SECONDS)).timestamp()),
        "type": "stream_ticket",
    }
    return jwt.encode(claims, secret, algorithm=settings.JWT_ALGORITHM)


def decode_stream_ticket(ticket: str, run_id: str) -> str:
    """Validate a stream ticket for ``run_id`` and return the user id.

    Raises:
        TokenExpiredError: ticket's ``exp`` is in the past.
        InvalidTokenError: signature mismatch, wrong token type (an access
            token is NOT accepted here), or run mismatch.
    """
    secret = _require_secret()
    try:
        claims = jwt.decode(ticket, secret, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("ticket has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError(f"invalid ticket: {exc}") from exc

    if not isinstance(claims, dict) or claims.get("type") != "stream_ticket":
        raise InvalidTokenError("token is not a stream ticket")
    sub = claims.get("sub")
    if not isinstance(sub, str):
        raise InvalidTokenError("ticket missing 'sub' claim")
    if claims.get("run_id") != run_id:
        raise InvalidTokenError("ticket is for a different run")
    return sub
