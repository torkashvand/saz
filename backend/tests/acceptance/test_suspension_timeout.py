"""Acceptance: SuspensionSweeper fails runs whose timeout has passed.

A run that suspends on human.approval or webhook.wait writes
``error.timeout_at`` (ISO timestamp). The sweeper periodically queries
for expired suspensions and transitions them to failed with
``SuspensionTimeout``. The suspended step must also be marked failed,
mirroring the webhook-reject contract (bug #3).

Driven synchronously via ``SuspensionSweeper.sweep_once()`` — the
background scheduler is disabled in tests.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step
from saz.engine.suspension_sweeper import SuspensionSweeper


@pytest.fixture
def expired_suspended_run(db_engine):
    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    with Session(db_engine) as session:
        flow = Flow(
            id="flow_acc_timeout",
            name="acc_timeout",
            definition={
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "approve",
                            "type": "human.approval",
                            "description": "Approve",
                        }
                    ],
                }
            },
        )
        run = Run(
            id="run_acc_timeout_1",
            flow_id="flow_acc_timeout",
            status="suspended",
            planner_mode="deterministic",
            payload={},
            error={
                "type": "HumanApprovalRequired",
                "step_id": "approve",
                "callback_id": "cb_acc_timeout",
                "timeout_at": past,
                "timeout_minutes": 1,
            },
        )
        step = Step(
            id="step_acc_timeout_1",
            run_id="run_acc_timeout_1",
            number=0,
            name="approve",
            step_type="human.approval",
            status="suspended",
            attempt=1,
        )
        session.add_all([flow, run, step])
        session.commit()
    return "run_acc_timeout_1", "step_acc_timeout_1"


def test_expired_suspension_is_failed_by_sweeper(expired_suspended_run, db_engine):
    run_id, step_id = expired_suspended_run

    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        interval_seconds=60,
        batch_limit=10,
        engine=db_engine,
    )
    swept = sweeper.sweep_once()

    assert swept >= 1, f"sweeper should have processed the expired run, got swept={swept}"

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        step = session.get(Step, step_id)
        assert run.status == "failed", f"run must be failed after timeout; got {run.status!r}"
        assert step.status == "failed", (
            f"the suspended step must also be failed (mirroring webhook reject); "
            f"got {step.status!r}"
        )
        # The sweeper preserves callback_id for late-callback idempotency
        assert run.error and run.error.get("callback_id") == "cb_acc_timeout"
