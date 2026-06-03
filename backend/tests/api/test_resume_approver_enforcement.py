"""The authenticated /resume path enforces the human.approval approvers list.

A non-admin user who is not named in ``approval.approvers`` cannot approve a
suspended run; a named user (or an admin) can. The approvers list is matched
against the user's username/email.
"""

import pytest
from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step
from tests.conftest import TEST_USER_ID, TEST_USER_USERNAME


def _seed_suspended(db_engine, approvers):
    with Session(db_engine) as session:
        session.add(
            Flow(
                created_by_user_id=TEST_USER_ID,
                id="flow_appr",
                name="Approval Flow",
                definition={"workflow": {"planner_mode": "deterministic"}},
            )
        )
        session.add(
            Run(
                created_by_user_id=TEST_USER_ID,
                id="run_appr",
                flow_id="flow_appr",
                status="suspended",
                planner_mode="deterministic",
                payload={},
                error={
                    "message": "Human approval required",
                    "type": "HumanApprovalRequired",
                    "step_id": "approve",
                    "callback_id": "cb123",
                    "approval": {"approvers": approvers},
                },
            )
        )
        session.add(
            Step(
                id="step_appr",
                run_id="run_appr",
                number=0,
                name="approve",
                step_type="human.approval",
                status="suspended",
            )
        )
        session.commit()
    return "run_appr"


def test_non_approver_is_forbidden(app_client, db_engine):
    _seed_suspended(db_engine, approvers=["someone.else@example.com"])
    resp = app_client.post("/api/v1/runs/run_appr/resume", json={"resume_data": {"approved": True}})
    assert resp.status_code == 403, resp.text
    # The run must remain suspended — a forbidden approval has no side effect.
    with Session(db_engine) as session:
        assert session.get(Run, "run_appr").status == "suspended"


def test_named_approver_can_resume(app_client, db_engine):
    _seed_suspended(db_engine, approvers=[TEST_USER_USERNAME])
    resp = app_client.post("/api/v1/runs/run_appr/resume", json={"resume_data": {"approved": True}})
    assert resp.status_code == 200, resp.text
    with Session(db_engine) as session:
        assert session.get(Run, "run_appr").status != "suspended"


@pytest.mark.parametrize("approvers", [None, []])
def test_no_approvers_allows_any_authenticated_user(app_client, db_engine, approvers):
    _seed_suspended(db_engine, approvers=approvers)
    resp = app_client.post("/api/v1/runs/run_appr/resume", json={"resume_data": {"approved": True}})
    assert resp.status_code == 200, resp.text
