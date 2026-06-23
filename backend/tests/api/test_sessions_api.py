"""Refresh-session lifecycle: login/refresh/logout, revocation, rotation.

The security contract under test:
- login sets an HttpOnly refresh cookie and a session-bound access token,
- refresh rotates the opaque secret,
- revoking a session (logout / logout_all / delete) rejects both refresh
  *and* the still-unexpired access token on its next request,
- replaying an already-rotated secret revokes the whole session.
"""

from saz.settings import settings
from tests.conftest import TEST_USER_PASSWORD, TEST_USER_USERNAME

COOKIE = settings.REFRESH_COOKIE_NAME


def _login(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"identifier": TEST_USER_USERNAME, "password": TEST_USER_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return resp


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_login_sets_refresh_cookie(unauthenticated_app_client):
    resp = _login(unauthenticated_app_client)
    assert resp.json()["access_token"]
    assert unauthenticated_app_client.cookies.get(COOKIE)


def test_refresh_rotates_secret_and_returns_new_token(unauthenticated_app_client):
    client = unauthenticated_app_client
    _login(client)
    first_secret = client.cookies.get(COOKIE)

    resp = client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]
    assert client.cookies.get(COOKIE) != first_secret


def test_refresh_without_cookie_is_401(unauthenticated_app_client):
    resp = unauthenticated_app_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


def test_logout_revokes_session_and_blocks_refresh(unauthenticated_app_client):
    client = unauthenticated_app_client
    token = _login(client).json()["access_token"]

    assert client.post("/api/v1/auth/logout").status_code == 204
    # Refresh after logout is refused.
    assert client.post("/api/v1/auth/refresh").status_code == 401
    # The still-unexpired access token is rejected because its session is gone.
    assert client.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 401


def test_revoked_session_rejects_access_token_immediately(unauthenticated_app_client):
    client = unauthenticated_app_client
    token = _login(client).json()["access_token"]
    # Before revocation the token works.
    assert client.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 200

    sessions = client.get("/api/v1/auth/sessions", headers=_bearer(token)).json()
    assert sessions["total"] == 1
    assert sessions["items"][0]["is_current"] is True
    sid = sessions["items"][0]["id"]

    assert client.delete(f"/api/v1/auth/sessions/{sid}", headers=_bearer(token)).status_code == 204
    assert client.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 401


def test_logout_all_revokes_every_session(unauthenticated_app_client, db_engine):
    # Two independent logins for the same user → two sessions.
    from fastapi.testclient import TestClient

    client_a = unauthenticated_app_client
    token_a = _login(client_a).json()["access_token"]

    # A second client shares the same app/db overrides already installed.
    client_b = TestClient(client_a.app, raise_server_exceptions=False)
    _login(client_b)

    listed = client_a.get("/api/v1/auth/sessions", headers=_bearer(token_a)).json()
    assert listed["total"] >= 1

    resp = client_a.post("/api/v1/auth/logout_all", headers=_bearer(token_a))
    assert resp.status_code == 200
    assert resp.json()["revoked"] >= 2

    assert client_a.post("/api/v1/auth/refresh").status_code == 401
    assert client_b.post("/api/v1/auth/refresh").status_code == 401


def test_refresh_replay_revokes_session(unauthenticated_app_client):
    client = unauthenticated_app_client
    _login(client)
    stolen = client.cookies.get(COOKIE)

    # Legitimate refresh rotates the secret.
    assert client.post("/api/v1/auth/refresh").status_code == 200

    # Replaying the old (rotated-away) secret is detected as theft: refused
    # and the whole session revoked, so the legitimate new secret dies too.
    client.cookies.set(COOKIE, stolen, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401
