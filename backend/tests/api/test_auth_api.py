"""API tests for /api/v1/auth/* endpoints and protected-route behavior.

There is intentionally no /api/v1/auth/register; user creation is admin-
only (see tests/api/test_admin_users_api.py).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from saz.db.models import User
from saz.security import hash_password
from tests.conftest import TEST_USER_ID, TEST_USER_PASSWORD, TEST_USER_USERNAME


def _seed_user(
    db_engine,
    *,
    username: str,
    password: str,
    email: str | None = None,
    is_active: bool = True,
    must_change_password: bool = False,
) -> str:
    """Insert a user row directly so the test does not depend on the
    admin API — keeps these tests focused on /auth behavior only.
    """
    user_id = f"user-{username}"
    with Session(db_engine) as s:
        s.add(
            User(
                id=user_id,
                username=username,
                email=email or f"{username}@example.com",
                password_hash=hash_password(password),
                is_active=is_active,
                must_change_password=must_change_password,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        s.commit()
    return user_id


# --- Registration endpoint is removed by design ---


def test_register_endpoint_does_not_exist(unauthenticated_app_client):
    resp = unauthenticated_app_client.post(
        "/api/v1/auth/register",
        json={"username": "x", "email": "x@x.com", "password": "hunter222"},
    )
    # 404 (no route) or 405 (no POST on that path). Anything 2xx would be
    # a public-registration regression and must fail loudly here.
    assert resp.status_code in (
        404,
        405,
    ), f"register endpoint resurrected (status={resp.status_code})"


def test_forgot_password_endpoint_does_not_exist(unauthenticated_app_client):
    for path in (
        "/api/v1/auth/forgot_password",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset_password",
        "/api/v1/auth/reset-password",
        "/api/v1/auth/password_reset",
    ):
        resp = unauthenticated_app_client.post(path, json={"email": "x@x.com"})
        assert resp.status_code in (404, 405), (
            f"public reset endpoint {path} unexpectedly exists " f"(status={resp.status_code})"
        )


# --- Login ---


def test_login_succeeds_with_valid_credentials(unauthenticated_app_client):
    resp = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": TEST_USER_USERNAME, "password": TEST_USER_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "access_token" in body
    assert body["user"]["username"] == TEST_USER_USERNAME
    assert "password_hash" not in body["user"]


def test_login_works_with_email_as_identifier(unauthenticated_app_client):
    resp = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "testuser@example.com", "password": TEST_USER_PASSWORD},
    )
    assert resp.status_code == 200, resp.text


def test_login_fails_with_wrong_password(unauthenticated_app_client):
    resp = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": TEST_USER_USERNAME, "password": "wrong-password"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert "invalid credentials" in (body.get("detail") or body.get("message") or "").lower()


def test_login_fails_with_unknown_user(unauthenticated_app_client):
    resp = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "nobody", "password": "any-password"},
    )
    assert resp.status_code == 401


def test_login_fails_for_disabled_user(unauthenticated_app_client, db_engine):
    _seed_user(db_engine, username="disabled", password="hunter222", is_active=False)
    resp = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "disabled", "password": "hunter222"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert "disabled" in (body.get("detail") or body.get("message") or "").lower()


# --- /me ---


def test_me_requires_authentication(unauthenticated_app_client):
    resp = unauthenticated_app_client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_me_returns_current_user_with_valid_token(unauthenticated_app_client):
    login = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": TEST_USER_USERNAME, "password": TEST_USER_PASSWORD},
    )
    token = login.json()["access_token"]
    resp = unauthenticated_app_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == TEST_USER_USERNAME
    # The seeded test user is an operator; role is the authorization source
    # of truth and must be exposed so the frontend can route accordingly.
    assert body["role"] == "operator"
    assert "is_admin" not in body
    assert "must_change_password" in body
    assert "password_hash" not in body


def test_me_rejects_garbage_token(unauthenticated_app_client):
    resp = unauthenticated_app_client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"}
    )
    assert resp.status_code == 401


def test_me_rejects_expired_token(unauthenticated_app_client, db_engine):
    from datetime import timedelta

    from saz.security import create_access_token

    expired, _ = create_access_token(
        user_id=TEST_USER_ID,
        username=TEST_USER_USERNAME,
        expires_delta=timedelta(seconds=-1),
    )
    resp = unauthenticated_app_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}
    )
    assert resp.status_code == 401


# --- Change password ---


def test_change_password_works(unauthenticated_app_client, db_engine):
    _seed_user(db_engine, username="changer", password="initial-pw-1")
    login = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "changer", "password": "initial-pw-1"},
    )
    token = login.json()["access_token"]

    resp = unauthenticated_app_client.post(
        "/api/v1/auth/change_password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "initial-pw-1", "new_password": "new-pw-9999"},
    )
    assert resp.status_code == 200, resp.text
    # The new password must work, the old must not.
    relogin_new = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "changer", "password": "new-pw-9999"},
    )
    assert relogin_new.status_code == 200
    relogin_old = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "changer", "password": "initial-pw-1"},
    )
    assert relogin_old.status_code == 401


def test_change_password_requires_current(unauthenticated_app_client, db_engine):
    _seed_user(db_engine, username="changer2", password="initial-pw-1")
    login = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "changer2", "password": "initial-pw-1"},
    )
    token = login.json()["access_token"]

    resp = unauthenticated_app_client.post(
        "/api/v1/auth/change_password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "wrong-current", "new_password": "new-pw-9999"},
    )
    assert resp.status_code == 400


def test_change_password_clears_forced_state(unauthenticated_app_client, db_engine):
    _seed_user(
        db_engine,
        username="forced",
        password="temp-pw-from-admin",
        must_change_password=True,
    )
    login = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "forced", "password": "temp-pw-from-admin"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is True
    token = login.json()["access_token"]

    resp = unauthenticated_app_client.post(
        "/api/v1/auth/change_password",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "temp-pw-from-admin",
            "new_password": "self-chosen-pw-1",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["must_change_password"] is False


# --- Forced-change blocks operational endpoints ---


def test_forced_password_change_blocks_operational_endpoints(unauthenticated_app_client, db_engine):
    _seed_user(
        db_engine,
        username="locked",
        password="temp-pw-from-admin",
        must_change_password=True,
    )
    login = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "locked", "password": "temp-pw-from-admin"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # /me + /change_password remain reachable
    assert unauthenticated_app_client.get("/api/v1/auth/me", headers=headers).status_code == 200

    # Operational endpoints reject with 403 + specific signal
    for path in (
        "/api/v1/flows",
        "/api/v1/runs",
        "/api/v1/credentials",
    ):
        resp = unauthenticated_app_client.get(path, headers=headers)
        assert resp.status_code == 403, (
            f"{path} should reject forced-change users with 403, " f"got {resp.status_code}"
        )
        # The header lets the frontend redirect to /change-password.
        assert resp.headers.get("X-Password-Change-Required") == "true"


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
        ("get", "/api/v1/admin/users"),
        ("post", "/api/v1/admin/users"),
    ],
)
def test_protected_routes_require_auth(unauthenticated_app_client, method, path):
    kwargs = {"json": {}} if method == "post" else {}
    resp = getattr(unauthenticated_app_client, method)(path, **kwargs)
    assert (
        resp.status_code == 401
    ), f"{method.upper()} {path} returned {resp.status_code}, expected 401"


def test_health_endpoints_remain_public(unauthenticated_app_client):
    resp = unauthenticated_app_client.get("/api/v1/healthz")
    assert resp.status_code in (200, 404)
    assert resp.status_code != 401


def test_webhook_callback_remains_public(unauthenticated_app_client):
    # Webhook callback uses an unguessable callback_id in the URL as its
    # own credential — external systems cannot send a JWT.
    resp = unauthenticated_app_client.post(
        "/api/v1/webhooks/callback/unknown-callback-id",
        json={"action": "approve"},
    )
    assert resp.status_code != 401
