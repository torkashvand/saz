"""Concurrent duplicate-callback stress.

External systems retry callbacks, so two POSTs to /webhooks/callback/{id}
can land at near-identical times. The endpoint must converge to exactly
one transition regardless of arrival order. The sequential idempotency
case is covered by tests/acceptance/test_callback_flow.py; this adds
real-thread concurrency.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step


@pytest.fixture
def suspended_run(db_engine):
    callback_id = "cb_concurrent_stress_777"
    with Session(db_engine) as session:
        flow = Flow(
            id="flow_concurrent",
            name="concurrent_stress",
            definition={
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "approve",
                            "type": "human.approval",
                            "description": "Concurrent approve gate",
                        }
                    ],
                }
            },
        )
        run = Run(
            id="run_concurrent_stress_1",
            flow_id="flow_concurrent",
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
            id="step_concurrent_stress_1",
            run_id="run_concurrent_stress_1",
            number=0,
            name="approve",
            step_type="human.approval",
            status="suspended",
            attempt=1,
        )
        session.add_all([flow, run, step])
        session.commit()
    return "run_concurrent_stress_1", callback_id


def test_concurrent_approve_callbacks_converge_to_one_transition(
    app_client, suspended_run, db_engine
):
    run_id, callback_id = suspended_run

    def fire():
        return app_client.post(
            f"/api/v1/webhooks/callback/{callback_id}",
            json={"action": "approve", "data": {"approver": "ops"}},
        )

    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(lambda _: fire(), range(5)))

    statuses = [r.status_code for r in responses]
    assert all(
        s == 200 for s in statuses
    ), f"every concurrent callback should land cleanly; got {statuses}"
    bodies = [r.json().get("status") for r in responses]
    resumed = [b for b in bodies if b == "resumed"]
    already = [b for b in bodies if b == "already_processed"]
    assert len(resumed) == 1, (
        f"exactly one of the 5 concurrent callbacks must transition to " f"resumed; got {bodies}"
    )
    assert len(resumed) + len(already) == len(responses), (
        f"every concurrent callback must be either resumed or already_processed; " f"got {bodies}"
    )

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        # After the (one) transition the run leaves "suspended". The sync
        # scheduler may have already picked it up and progressed it further
        # (running / failed / completed), which is fine — the point of this
        # test is that concurrent callbacks did not leave it stuck or
        # double-transition.
        assert run.status != "suspended", (
            "concurrent callbacks must have moved the run out of suspended; " f"got {run.status!r}"
        )
