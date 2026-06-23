"""Viewer-tier authorization: read allowed, writes refused.

``viewer`` is the read-only tier. The security boundary lives in the
``get_operator_user`` dependency, not the UI — these tests pin both the
dependency itself and a representative mutating endpoint so a viewer can
never create or change persisted state.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from saz.api.dependencies import get_operator_user
from saz.db.models import User
from saz.domain.literals import Role
from tests.conftest import TEST_USER_ID


def _user(role: Role) -> User:
    return User(id="x", username="u", email="u@example.com", password_hash="h", role=role)


def test_operator_dependency_allows_admin_and_operator():
    for role in (Role.ADMIN, Role.OPERATOR):
        user = _user(role)
        assert get_operator_user(user=user) is user


def test_operator_dependency_blocks_viewer():
    with pytest.raises(HTTPException) as exc:
        get_operator_user(user=_user(Role.VIEWER))
    assert exc.value.status_code == 403
    assert exc.value.detail == "write access required"


@pytest.fixture
def viewer_user(db_engine):
    """Demote the seeded user (operator by default) to viewer so app_client,
    which authenticates as that user, exercises the read-only tier."""
    with Session(db_engine) as s:
        u = s.get(User, TEST_USER_ID)
        assert u is not None
        u.role = Role.VIEWER
        s.commit()
    yield


def test_viewer_cannot_create_credential(app_client, viewer_user):
    resp = app_client.post(
        "/api/v1/credentials",
        json={"name": "secret1", "type": "api_token", "data": {"token": "abc"}},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "write access required"


def test_viewer_cannot_register_flow(app_client, viewer_user):
    resp = app_client.post("/api/v1/flows", json={"yaml": "name: x"})
    assert resp.status_code == 403


def test_viewer_can_read_credentials(app_client, viewer_user):
    resp = app_client.get("/api/v1/credentials")
    assert resp.status_code == 200


def test_operator_can_create_credential(app_client):
    # The seeded user is an operator by default — writes must still work.
    resp = app_client.post(
        "/api/v1/credentials",
        json={"name": "secret2", "type": "api_token", "data": {"token": "abc"}},
    )
    assert resp.status_code == 200, resp.text
