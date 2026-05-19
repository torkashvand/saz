"""Acceptance: webhook callback resumes a suspended run, duplicate is idempotent.

External callers may POST to /webhooks/callback/{id} more than once for
the same suspended run — retries, double-clicks, queue redelivery. The
endpoint must:
  - transition the run on the FIRST callback (approve or reject),
  - mark the suspended step terminal (this is what bug #3 fixed),
  - return ``already_processed`` on subsequent callbacks without changing
    state again.

This goes through the real FastAPI route via ``app_client`` rather than
calling the service directly, so the route+repo+emitter wiring is in
scope.
"""

import pytest
from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step


@pytest.fixture
def suspended_run(db_engine):
    callback_id = "cb_acc_callback_xyz123"
    with Session(db_engine) as session:
        flow = Flow(
            id="flow_acc_callback",
            name="acc_callback",
            definition={
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "approve",
                            "type": "human.approval",
                            "description": "Approve change",
                        }
                    ],
                }
            },
        )
        run = Run(
            id="run_acc_callback_1",
            flow_id="flow_acc_callback",
            status="suspended",
            planner_mode="deterministic",
            payload={},
            error={
                "type": "HumanApprovalRequired",
                "step_id": "approve",
                "callback_id": callback_id,
            },
        )
        step = Step(
            id="step_acc_callback_1",
            run_id="run_acc_callback_1",
            number=0,
            name="approve",
            step_type="human.approval",
            status="suspended",
            attempt=1,
        )
        session.add_all([flow, run, step])
        session.commit()
    return "run_acc_callback_1", "step_acc_callback_1", callback_id


def test_approve_callback_resumes_then_duplicate_is_idempotent(
    app_client, suspended_run, db_engine
):
    run_id, step_id, callback_id = suspended_run

    first = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "approve", "data": {"approver": "ops@example.com"}},
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "resumed"

    with Session(db_engine) as session:
        step = session.get(Step, step_id)
        assert step is not None
        assert (
            step.status == "completed"
        ), f"after approve, gate step must be completed; got {step.status!r}"
        assert step.output and step.output.get("approver") == "ops@example.com"

    second = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "approve", "data": {"approver": "ops@example.com"}},
    )
    assert second.status_code == 200, second.text
    assert (
        second.json()["status"] == "already_processed"
    ), f"duplicate callback must be idempotent; got {second.json()!r}"

    with Session(db_engine) as session:
        step = session.get(Step, step_id)
        assert step.status == "completed", "duplicate must not regress step state"


def test_reject_callback_fails_step_and_run(app_client, suspended_run, db_engine):
    run_id, step_id, callback_id = suspended_run

    response = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "reject", "reason": "Budget exhausted"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        step = session.get(Step, step_id)
        assert run.status == "failed"
        assert step.status == "failed"
        assert step.error and "Budget exhausted" in str(step.error)
