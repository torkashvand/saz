"""Unit tests for JWT access tokens."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from saz.security.tokens import (
    InvalidTokenError,
    TokenExpiredError,
    create_access_token,
    decode_access_token,
)
from saz.settings import settings


def test_create_and_decode_roundtrip():
    token, expires_at = create_access_token("user-id-1", "alice")
    claims = decode_access_token(token)
    assert claims["sub"] == "user-id-1"
    assert claims["username"] == "alice"
    assert claims["type"] == "access"
    # exp claim must match the returned expires_at within a second.
    assert abs(claims["exp"] - int(expires_at.timestamp())) <= 1


def test_decode_rejects_garbage_string():
    with pytest.raises(InvalidTokenError):
        decode_access_token("not-a-token")


def test_decode_rejects_token_signed_with_wrong_secret():
    payload = {
        "sub": "u",
        "username": "x",
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        "type": "access",
    }
    forged = jwt.encode(payload, "different-secret", algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(InvalidTokenError):
        decode_access_token(forged)


def test_decode_rejects_expired_token():
    token, _ = create_access_token("u", "x", expires_delta=timedelta(seconds=-1))
    with pytest.raises(TokenExpiredError):
        decode_access_token(token)


def test_decode_rejects_token_without_sub():
    # Build a hand-signed token missing 'sub' so we test the structural check.
    payload = {
        "username": "x",
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        "type": "access",
    }
    bad = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(InvalidTokenError):
        decode_access_token(bad)


def test_decode_rejects_non_access_token():
    payload = {
        "sub": "u",
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        "type": "refresh",
    }
    other = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(InvalidTokenError):
        decode_access_token(other)
