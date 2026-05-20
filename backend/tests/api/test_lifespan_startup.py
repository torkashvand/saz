"""Lifespan startup validation: missing JWT_SECRET_KEY must fail loud.

Operators who forget to set ``JWT_SECRET_KEY`` previously got a server
that booted fine and then 500'd on every login attempt. Worse, because
exception responses lost their CORS headers, the frontend reported a
misleading "Connection issue. Please check your network…" Crashing on
boot with the actual reason in the log saves that round trip.
"""

import pytest
from fastapi.testclient import TestClient

from saz.api import create_app
from saz.settings import settings


def test_startup_raises_when_jwt_secret_is_missing(monkeypatch):
    """An empty JWT_SECRET_KEY must abort startup with a clear error."""
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "")

    app = create_app()
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY is not configured"):
        with TestClient(app):
            pass


def test_startup_succeeds_when_jwt_secret_is_set(monkeypatch):
    """Sanity-check the inverse so a future refactor that always raises
    is caught immediately."""
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "test-secret-from-monkeypatch")

    app = create_app()
    # Entering the context manager runs lifespan startup; exiting runs
    # shutdown. If startup raises, this block re-raises.
    with TestClient(app) as client:
        # Health endpoint is the simplest signal that startup completed.
        resp = client.get("/health")
        assert resp.status_code in (200, 503)  # 503 if DB probe fails — still booted
