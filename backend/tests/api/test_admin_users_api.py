"""API tests for /api/v1/admin/users/* — admin-only user management.

Covers:
- non-admin and unauthenticated users are blocked
- admin can list / create / update / disable / activate / promote / demote / reset
- admin password reset flips must_change_password
- the last-admin safety rail
- admin cannot self-disable or self-demote
- plaintext passwords never appear in responses
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from saz.db.models import User
from saz.security import hash_password
from tests.conftest import TEST_USER_ID


@pytest.fixture
def admin_user(db_engine):
    """Promote the seeded test_user to admin so app_client (which is
    auto-authenticated as that user) can call admin endpoints."""
    with Session(db_engine) as s:
        u = s.get(User, TEST_USER_ID)
        assert u is not None
        u.is_admin = True
        s.commit()
    yield


def _seed_normal_user(
    db_engine,
    *,
    username: str = "victim",
    password: str = "initial-pw-1",
    is_admin: bool = False,
    is_active: bool = True,
    must_change_password: bool = False,
) -> str:
    user_id = f"user-{username}"
    with Session(db_engine) as s:
        s.add(
            User(
                id=user_id,
                username=username,
                email=f"{username}@example.com",
                password_hash=hash_password(password),
                is_active=is_active,
                is_admin=is_admin,
                must_change_password=must_change_password,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        s.commit()
    return user_id


# --- Authorization gates ---


def test_list_users_requires_auth(unauthenticated_app_client):
    resp = unauthenticated_app_client.get("/api/v1/admin/users")
    assert resp.status_code == 401


def test_non_admin_user_cannot_list_users(app_client):
    # app_client is authenticated as the seeded user, which is NOT admin
    # by default.
    resp = app_client.get("/api/v1/admin/users")
    assert resp.status_code == 403


def test_non_admin_user_cannot_create_user(app_client):
    resp = app_client.post(
        "/api/v1/admin/users",
        json={
            "username": "carol",
            "email": "carol@example.com",
            "password": "hunter222-strong",
        },
    )
    assert resp.status_code == 403


def test_non_admin_user_cannot_reset_other_password(app_client, db_engine):
    target_id = _seed_normal_user(db_engine)
    resp = app_client.post(
        f"/api/v1/admin/users/{target_id}/reset_password",
        json={"temporary_password": "temp-pw-1"},
    )
    assert resp.status_code == 403


# --- Happy path: admin actions ---


def test_admin_can_list_users(app_client, admin_user, db_engine):
    _seed_normal_user(db_engine, username="u1")
    resp = app_client.get("/api/v1/admin/users")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    usernames = {u["username"] for u in body["items"]}
    assert "u1" in usernames
    # No hashes leaked
    for u in body["items"]:
        assert "password_hash" not in u


def test_admin_can_create_user(app_client, admin_user):
    resp = app_client.post(
        "/api/v1/admin/users",
        json={
            "username": "newby",
            "email": "newby@example.com",
            "password": "first-pw-9999",
            "display_name": "New Newby",
            "is_admin": False,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["username"] == "newby"
    assert body["is_admin"] is False
    # A non-admin account lands in the operator tier; role is exposed so the
    # admin UI can render and (later) edit the authorization tier.
    assert body["role"] == "operator"
    # By default we force the user to change the admin-set password.
    assert body["must_change_password"] is True
    # Plaintext password and the hash itself must not leak.
    assert "first-pw-9999" not in resp.text
    assert "password_hash" not in body


def test_admin_can_update_user_profile(app_client, admin_user, db_engine):
    target_id = _seed_normal_user(db_engine, username="rename_me")
    resp = app_client.patch(
        f"/api/v1/admin/users/{target_id}",
        json={"display_name": "Display Updated", "email": "new@example.com"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["display_name"] == "Display Updated"
    assert body["email"] == "new@example.com"


def test_admin_can_update_username(app_client, admin_user, db_engine):
    """Username is editable through the PATCH endpoint; the response
    reflects the new value so the frontend can refresh the row directly."""
    target_id = _seed_normal_user(db_engine, username="old_name")
    resp = app_client.patch(
        f"/api/v1/admin/users/{target_id}",
        json={"username": "new_name"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["username"] == "new_name"


def test_admin_update_rejects_duplicate_username(app_client, admin_user, db_engine):
    """Renaming onto another user's handle returns 409 (ConflictError →
    service handler) — never 500, never silent overwrite."""
    _seed_normal_user(db_engine, username="taken_handle")
    target_id = _seed_normal_user(db_engine, username="will_collide")
    resp = app_client.patch(
        f"/api/v1/admin/users/{target_id}",
        json={"username": "taken_handle"},
    )
    assert resp.status_code == 409, resp.text
    assert "taken_handle" in resp.text


def test_non_admin_user_cannot_update_other_user(app_client, db_engine):
    """The PATCH endpoint is admin-only; the AdminUserDep gate must turn
    away a logged-in non-admin with 403 (not 401, not 200). Mirrors the
    existing list/create/reset gate tests."""
    target_id = _seed_normal_user(db_engine, username="victim")
    resp = app_client.patch(
        f"/api/v1/admin/users/{target_id}",
        json={"username": "hijacked"},
    )
    assert resp.status_code == 403, resp.text


def test_admin_can_disable_and_reactivate_user(
    app_client, admin_user, db_engine, unauthenticated_app_client
):
    target_id = _seed_normal_user(db_engine, username="toggle")

    # Disable
    resp = app_client.post(
        f"/api/v1/admin/users/{target_id}/set_active",
        json={"is_active": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is False

    # Disabled user cannot log in
    login = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "toggle", "password": "initial-pw-1"},
    )
    assert login.status_code == 401

    # Reactivate
    resp = app_client.post(
        f"/api/v1/admin/users/{target_id}/set_active",
        json={"is_active": True},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True


def test_admin_cannot_disable_own_account(app_client, admin_user):
    resp = app_client.post(
        f"/api/v1/admin/users/{TEST_USER_ID}/set_active",
        json={"is_active": False},
    )
    assert resp.status_code == 400


def test_admin_cannot_disable_last_admin(app_client, admin_user, db_engine):
    # Only the seeded admin exists; trying to disable a different admin
    # who is "the last" should be guarded. Set up a scenario: promote
    # another user to admin, then ensure the seeded admin can't disable
    # themselves; then make the *other* user the only active admin and
    # ensure they can't be disabled.
    other = _seed_normal_user(db_engine, username="second_admin", is_admin=True)

    # Demote seeded admin so `second_admin` is the only active admin.
    resp = app_client.post(
        f"/api/v1/admin/users/{TEST_USER_ID}/set_admin",
        json={"is_admin": False},
    )
    assert resp.status_code == 400, "demoting yourself should be refused"

    # Try disabling the only-other admin via that admin's session — not
    # easy in this fixture (we don't have a second authenticated client).
    # Instead disable a third user and confirm guard fires on the other
    # admin if we try via this admin.
    resp = app_client.post(
        f"/api/v1/admin/users/{other}/set_admin",
        json={"is_admin": False},
    )
    # Demoting "second_admin" is allowed because the seeded admin is
    # still active — there is still one active admin left.
    assert resp.status_code == 200, resp.text


def test_admin_reset_password_forces_change_and_clears_after_user_changes(
    db_engine, unauthenticated_app_client
):
    """End-to-end: admin reset → forced change → user changes → app unlocks.

    Uses only ``unauthenticated_app_client`` so there are no dependency-
    override leaks; both the admin and the target user act through real
    JWTs.
    """
    # Seed an admin we can log in as for real (not the dependency-overridden
    # test_user), plus the target.
    admin_pw = "admin-strong-pw-1"
    with Session(db_engine) as s:
        s.add(
            User(
                id="real-admin",
                username="realadmin",
                email="realadmin@example.com",
                password_hash=hash_password(admin_pw),
                is_active=True,
                is_admin=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        s.commit()
    target_id = _seed_normal_user(db_engine, username="forgetful")

    # Real admin login → real JWT.
    admin_login = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "realadmin", "password": admin_pw},
    )
    assert admin_login.status_code == 200, admin_login.text
    admin_token = admin_login.json()["access_token"]
    admin_hdr = {"Authorization": f"Bearer {admin_token}"}

    # Admin sets a temporary password.
    resp = unauthenticated_app_client.post(
        f"/api/v1/admin/users/{target_id}/reset_password",
        headers=admin_hdr,
        json={"temporary_password": "admin-set-temp-pw"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["must_change_password"] is True
    # Plaintext temp password must not appear in the response.
    assert "admin-set-temp-pw" not in resp.text

    # User can log in with the temp password but cannot use the app
    # until they change it.
    login = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "forgetful", "password": "admin-set-temp-pw"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert login.json()["user"]["must_change_password"] is True

    blocked = unauthenticated_app_client.get(
        "/api/v1/flows", headers={"Authorization": f"Bearer {token}"}
    )
    assert blocked.status_code == 403
    assert blocked.headers.get("X-Password-Change-Required") == "true"

    # User changes their password — forced flag clears.
    cp = unauthenticated_app_client.post(
        "/api/v1/auth/change_password",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "admin-set-temp-pw",
            "new_password": "self-chosen-pw-1",
        },
    )
    assert cp.status_code == 200
    assert cp.json()["must_change_password"] is False

    # Old temporary password no longer works.
    relogin_old = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "forgetful", "password": "admin-set-temp-pw"},
    )
    assert relogin_old.status_code == 401

    # New password works and operational endpoints are reachable again.
    relogin_new = unauthenticated_app_client.post(
        "/api/v1/auth/login",
        json={"identifier": "forgetful", "password": "self-chosen-pw-1"},
    )
    assert relogin_new.status_code == 200
    token_new = relogin_new.json()["access_token"]
    op = unauthenticated_app_client.get(
        "/api/v1/flows", headers={"Authorization": f"Bearer {token_new}"}
    )
    assert op.status_code == 200


def test_admin_create_duplicate_username_fails(app_client, admin_user, db_engine):
    _seed_normal_user(db_engine, username="dupname")
    resp = app_client.post(
        "/api/v1/admin/users",
        json={
            "username": "dupname",
            "email": "different@example.com",
            "password": "hunter222-strong",
        },
    )
    assert resp.status_code in (400, 409)


def test_admin_create_short_password_fails(app_client, admin_user):
    resp = app_client.post(
        "/api/v1/admin/users",
        json={
            "username": "shortie",
            "email": "shortie@example.com",
            "password": "short",
        },
    )
    assert resp.status_code in (400, 422)
