"""Webhook reject must fail the suspended step, not just the run.

Bug being pinned: in webhooks.py, the reject branch calls
uow.runs.mark_failed(...) and emits approval_denied/run_failed events but
never touches the suspended Step. The step stays at status='suspended' on a
failed run, which:
  - breaks the timeline UI (a failed run can still have a "suspended" step)
  - leaves no rejection reason on Step.error for audit
  - confuses any consumer that expects terminal step states on a terminal run

Compare to the approve branch which calls steps.mark_completed() and writes
the resume payload to step.output.
"""

import pytest
from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step
from tests.conftest import TEST_USER_ID


@pytest.fixture
def suspended_with_callback(db_engine):
    """Suspended run with a callback_id, ready for /webhooks/callback/{id}."""
    callback_id = "cb_reject_test_xyz789"
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_reject_step",
            name="reject_step_state",
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
                },
            },
        )
        session.add(flow)

        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_reject_step_1",
            flow_id="flow_reject_step",
            status="suspended",
            planner_mode="deterministic",
            payload={},
            error={
                "type": "HumanApprovalRequired",
                "step_id": "approve",
                "callback_id": callback_id,
            },
        )
        session.add(run)

        step = Step(
            id="step_reject_1",
            run_id="run_reject_step_1",
            number=0,
            name="approve",
            step_type="human.approval",
            status="suspended",
            attempt=1,
        )
        session.add(step)
        session.commit()

    return "run_reject_step_1", "step_reject_1", callback_id


def test_webhook_reject_marks_suspended_step_failed(app_client, suspended_with_callback, db_engine):
    run_id, step_id, callback_id = suspended_with_callback

    response = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "reject", "reason": "Insufficient budget"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run.status == "failed", "Run status assertion is a sanity check"

        step = session.get(Step, step_id)
        assert step is not None
        assert step.status != "suspended", (
            "A failed run must not still have a 'suspended' step. " f"step.status={step.status!r}"
        )
        assert (
            step.status == "failed"
        ), f"Reject should fail the gate step. Got status={step.status!r}"


def test_webhook_reject_records_reason_in_step_error(
    app_client, suspended_with_callback, db_engine
):
    run_id, step_id, callback_id = suspended_with_callback

    response = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "reject", "reason": "Insufficient budget"},
    )
    assert response.status_code == 200, response.text

    with Session(db_engine) as session:
        step = session.get(Step, step_id)
        assert step.error, (
            "Rejected gate step must record the rejection on Step.error so "
            "operators see WHY it failed without digging through run.error"
        )
        as_text = str(step.error)
        assert (
            "Insufficient budget" in as_text
        ), f"Step.error should preserve the rejection reason. Got: {step.error!r}"
