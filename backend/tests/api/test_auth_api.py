"""API tests for /api/v1/auth/* endpoints and protected-route behavior."""

import pytest


def _register(client, username="alice", email="alice@example.com", password="hunter222"):
    return client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": email, "password": password},
    )


def test_register_returns_token_and_user(unauthenticated_app_client):
    resp = _register(unauthenticated_app_client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "access_token" in body and body["access_token"]
    assert body["token_type"] == "bearer"
    assert "expires_at" in body
    assert body["user"]["username"] == "alice"
    assert body["user"]["email"] == "alice@example.com"
    # The hash must never leak in the response.
    assert "password_hash" not in body["user"]
    assert "password" not in resp.text


def test_register_rejects_duplicate_username(unauthenticated_app_client):
    _register(unauthenticated_app_client)
    resp = _register(unauthenticated_app_client, email="other@example.com")
    assert resp.status_code in (400, 409)


def test_register_rejects_short_password(unauthenticated_app_client):
    resp = unauthenticated_app_client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "email": "a@example.com", "password": "short"},
    )
    assert resp.status_code in (400, 422)


def test_login_succeeds_with_valid_credentials(unauthenticated_app_client):
    _register(unauthenticated_app_client)
    resp = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "alice", "password": "hunter222"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "access_token" in body
    assert body["user"]["username"] == "alice"


def test_login_works_with_email_as_identifier(unauthenticated_app_client):
    _register(unauthenticated_app_client)
    resp = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "alice@example.com", "password": "hunter222"},
    )
    assert resp.status_code == 200, resp.text


def test_login_fails_with_wrong_password(unauthenticated_app_client):
    _register(unauthenticated_app_client)
    resp = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "alice", "password": "wrong-password"},
    )
    assert resp.status_code == 401
    # Message must be generic — must not reveal whether the user exists.
    body = resp.json()
    assert "invalid credentials" in (body.get("detail") or body.get("message") or "").lower()


def test_login_fails_with_unknown_user(unauthenticated_app_client):
    resp = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "nobody", "password": "any-password"},
    )
    assert resp.status_code == 401


def test_me_requires_authentication(unauthenticated_app_client):
    resp = unauthenticated_app_client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_me_returns_current_user_with_valid_token(unauthenticated_app_client):
    reg = _register(unauthenticated_app_client)
    token = reg.json()["access_token"]
    resp = unauthenticated_app_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "alice"
    assert "password_hash" not in body


def test_me_rejects_garbage_token(unauthenticated_app_client):
    resp = unauthenticated_app_client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"}
    )
    assert resp.status_code == 401


def test_me_rejects_expired_token(unauthenticated_app_client, db_engine):
    from datetime import timedelta

    from saz.security import create_access_token
    from tests.conftest import TEST_USER_ID, TEST_USER_USERNAME

    expired, _ = create_access_token(
        user_id=TEST_USER_ID,
        username=TEST_USER_USERNAME,
        expires_delta=timedelta(seconds=-1),
    )
    resp = unauthenticated_app_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}
    )
    assert resp.status_code == 401


# --- Protected routes reject unauthenticated calls ---


@pytest.mark.parametrize(
    "method, path",
    [
        ("get", "/api/v1/flows"),
        ("post", "/api/v1/flows"),
        ("get", "/api/v1/runs"),
        ("post", "/api/v1/runs"),
        ("get", "/api/v1/credentials"),
        ("post", "/api/v1/credentials"),
        ("get", "/api/v1/auth/me"),
    ],
)
def test_protected_routes_require_auth(unauthenticated_app_client, method, path):
    kwargs = {"json": {}} if method == "post" else {}
    resp = getattr(unauthenticated_app_client, method)(path, **kwargs)
    assert (
        resp.status_code == 401
    ), f"{method.upper()} {path} returned {resp.status_code}, expected 401"


def test_health_endpoints_remain_public(unauthenticated_app_client):
    # Health endpoints exist for orchestrators and must not require auth.
    resp = unauthenticated_app_client.get("/api/v1/healthz")
    assert resp.status_code in (200, 404)  # 404 if path differs; never 401.
    assert resp.status_code != 401


def test_webhook_callback_remains_public(unauthenticated_app_client):
    # Webhook callback uses an unguessable callback_id in the URL as its
    # own credential — external systems cannot send a JWT. The endpoint
    # must remain reachable without one (it returns 404 for an unknown
    # callback_id but never 401).
    resp = unauthenticated_app_client.post(
        "/api/v1/webhooks/callback/unknown-callback-id",
        json={"action": "approve"},
    )
    assert resp.status_code != 401
