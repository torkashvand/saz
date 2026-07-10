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
from saz.db.models import Flow, Run, Step, User
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


@pytest.fixture
def owned_suspended_run(db_engine):
    """A suspended approval-gate run owned by the seeded user (no approver
    allowlist, so the owner path of /resume authorizes it)."""
    with Session(db_engine) as session:
        session.add(
            Flow(
                created_by_user_id=TEST_USER_ID,
                id="flow_viewer_resume",
                name="Viewer Resume Flow",
                definition={
                    "workflow": {
                        "planner_mode": "deterministic",
                        "steps": [
                            {
                                "id": "gate",
                                "type": "human.approval",
                                "description": "Approve",
                            }
                        ],
                    },
                },
            )
        )
        session.commit()
        session.add(
            Run(
                created_by_user_id=TEST_USER_ID,
                id="run_viewer_resume",
                flow_id="flow_viewer_resume",
                status="suspended",
                planner_mode="deterministic",
                payload={},
                error={
                    "message": "Human approval required",
                    "type": "HumanApprovalRequired",
                    "step_id": "gate",
                    "callback_id": "cb_viewer_resume",
                },
            )
        )
        session.add(
            Step(
                id="step_viewer_resume",
                run_id="run_viewer_resume",
                number=0,
                name="gate",
                step_type="human.approval",
                status="suspended",
            )
        )
        session.commit()
    return "run_viewer_resume"


def test_viewer_cannot_resume_own_run(app_client, owned_suspended_run, viewer_user, db_engine):
    """Resume/reject mutate run state; a demoted viewer must be turned away
    even from runs they own, mirroring retry (OperatorUserDep)."""
    resp = app_client.post(
        f"/api/v1/runs/{owned_suspended_run}/resume",
        json={"resume_data": {"approved": True}},
    )
    assert resp.status_code == 403

    # The run must still be suspended — no state change happened.
    with Session(db_engine) as s:
        run = s.get(Run, owned_suspended_run)
        assert run is not None and run.status == "suspended"


def test_viewer_cannot_reject_own_run(app_client, owned_suspended_run, viewer_user, db_engine):
    resp = app_client.post(
        f"/api/v1/runs/{owned_suspended_run}/resume",
        json={"resume_data": {"approved": False, "reason": "nope"}},
    )
    assert resp.status_code == 403
    with Session(db_engine) as s:
        run = s.get(Run, owned_suspended_run)
        assert run is not None and run.status == "suspended"


def test_viewer_named_approver_can_still_approve(app_client, db_engine, viewer_user):
    """The approver allowlist is deliberately role-agnostic: a named approver
    (even a viewer) may act on the gate. Only the owner fallback is
    operator-gated."""
    with Session(db_engine) as session:
        seeded = session.get(User, TEST_USER_ID)
        assert seeded is not None
        session.add(
            Flow(
                created_by_user_id=TEST_USER_ID,
                id="flow_viewer_approver",
                name="Viewer Approver Flow",
                definition={
                    "workflow": {
                        "planner_mode": "deterministic",
                        "steps": [
                            {
                                "id": "gate",
                                "type": "human.approval",
                                "description": "Approve",
                            }
                        ],
                    },
                },
            )
        )
        session.commit()
        session.add(
            Run(
                created_by_user_id=TEST_USER_ID,
                id="run_viewer_approver",
                flow_id="flow_viewer_approver",
                status="suspended",
                planner_mode="deterministic",
                payload={},
                error={
                    "message": "Human approval required",
                    "type": "HumanApprovalRequired",
                    "step_id": "gate",
                    "callback_id": "cb_viewer_approver",
                    "approval": {"approvers": [seeded.username]},
                },
            )
        )
        session.add(
            Step(
                id="step_viewer_approver",
                run_id="run_viewer_approver",
                number=0,
                name="gate",
                step_type="human.approval",
                status="suspended",
            )
        )
        session.commit()

    resp = app_client.post(
        "/api/v1/runs/run_viewer_approver/resume",
        json={"resume_data": {"approved": True}},
    )
    assert resp.status_code == 200, resp.text
