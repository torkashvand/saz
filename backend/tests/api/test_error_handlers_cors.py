"""Regression tests: exception responses must carry CORS headers.

Without these headers the browser sees a 500 as a CORS-blocked network
failure, and the frontend mistranslates a real server error into
"Connection issue. Please check your network and try again." Both
handlers (service errors and the catch-all) are tested.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from saz.api.errors import (
    NotFoundError,
    ServiceError,
    generic_error_handler,
    service_error_handler,
    value_error_handler,
)
from saz.settings import settings


@pytest.fixture
def errorful_client():
    """Minimal app exposing routes that raise each handled exception kind.

    Using a fresh app keeps these tests independent of the real saz app
    so adding new routes doesn't change the surface under test.
    """
    app = FastAPI()
    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(ValueError, value_error_handler)
    app.add_exception_handler(Exception, generic_error_handler)

    @app.get("/boom-service")
    def boom_service() -> None:
        raise NotFoundError("nope")

    @app.get("/boom-value")
    def boom_value() -> None:
        raise ValueError("bad input")

    @app.get("/boom-generic")
    def boom_generic() -> None:
        raise RuntimeError("totally unexpected")

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_service_error_response_carries_cors_headers(errorful_client):
    origin = settings.ALLOWED_ORIGINS[0]
    resp = errorful_client.get("/boom-service", headers={"Origin": origin})
    assert resp.status_code == 404
    assert resp.headers.get("access-control-allow-origin") == origin
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_value_error_response_carries_cors_headers(errorful_client):
    origin = settings.ALLOWED_ORIGINS[0]
    resp = errorful_client.get("/boom-value", headers={"Origin": origin})
    assert resp.status_code == 400
    assert resp.headers.get("access-control-allow-origin") == origin


def test_generic_500_response_carries_cors_headers(errorful_client):
    """The bug this fixes: JWT_SECRET_KEY missing → InvalidTokenError →
    generic_error_handler → 500. Without CORS headers the browser reports
    the 500 as a network failure and the UI says "Connection issue"."""
    origin = settings.ALLOWED_ORIGINS[0]
    resp = errorful_client.get("/boom-generic", headers={"Origin": origin})
    assert resp.status_code == 500
    assert resp.headers.get("access-control-allow-origin") == origin
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_disallowed_origin_does_not_get_cors_echo(errorful_client):
    """Spoofed origins must not be reflected back — that would defeat
    the allow-list."""
    resp = errorful_client.get("/boom-generic", headers={"Origin": "https://evil.example.com"})
    assert resp.status_code == 500
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}


def test_request_without_origin_gets_no_cors_headers(errorful_client):
    """Non-browser callers (no Origin header) shouldn't see CORS headers."""
    resp = errorful_client.get("/boom-generic")
    assert resp.status_code == 500
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}
