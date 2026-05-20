"""Resume endpoint must advance the suspended step, not just re-queue the run.

Bug being pinned: RunService.resume_run() only marks the suspended step
completed when resume_data is truthy. Empty/null resume payloads move the run
back to "queued" while the gate step stays "suspended", so on the next pass
the executor neither skips it (only completed steps are restored) nor knows
it has already been resolved.

The existing test_resume_with_empty_resume_data only asserts run.status moved
off "suspended", which the bug satisfies. This file tightens the assertion to
step-level state and explicit gate semantics.
"""

import pytest
from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step
from tests.conftest import TEST_USER_ID


@pytest.fixture
def suspended_run(db_engine):
    """Run suspended at a human.approval gate. Mirrors test_resume_endpoint fixture."""
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_resume_nodata",
            name="resume_nodata",
            definition={
                "schema_version": 1,
                "flow": {"name": "resume_nodata", "description": "test"},
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "approve",
                            "type": "human.approval",
                            "description": "Review",
                        },
                        {
                            "id": "act",
                            "type": "tool.call",
                            "description": "Act after approval",
                            "tool": "http_request",
                            "params": {"url": "https://example.com"},
                        },
                    ],
                },
            },
        )
        session.add(flow)
        session.commit()

        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_resume_nodata_1",
            flow_id="flow_resume_nodata",
            status="suspended",
            planner_mode="deterministic",
            payload={},
            error={
                "type": "HumanApprovalRequired",
                "step_id": "approve",
                "callback_id": "cb_nodata_x",
            },
        )
        session.add(run)

        suspended_step = Step(
            id="step_approve_1",
            run_id="run_resume_nodata_1",
            number=0,
            name="approve",
            step_type="human.approval",
            status="suspended",
            attempt=1,
        )
        session.add(suspended_step)
        session.commit()

    return "run_resume_nodata_1", "step_approve_1"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="empty_body"),
        pytest.param({"resume_data": None}, id="explicit_null_resume_data"),
    ],
)
def test_resume_without_resume_data_completes_the_suspended_step(
    app_client, suspended_run, db_engine, body
):
    """Resuming should never leave the gate step in 'suspended' state.

    Today RunService.resume_run() does:
        if suspended_step and resume_data:
            ... mark_completed ...
    so a missing/null resume_data flips the run back to "queued" but leaves
    the human.approval step record at status='suspended'. On the next
    executor pass the gate is neither skipped (only completed steps are
    skipped) nor explicitly resolved.
    """
    run_id, step_id = suspended_run

    response = app_client.post(f"/api/v1/runs/{run_id}/resume", json=body)
    assert response.status_code == 200, response.text

    with Session(db_engine) as session:
        step = session.get(Step, step_id)
        assert step is not None
        assert step.status != "suspended", (
            f"After resume with body={body}, the suspended gate step is "
            f"still status='suspended'. The executor will re-enter the "
            f"same gate or never advance it."
        )
        assert step.status == "completed", (
            f"Expected suspended gate to be marked completed on resume, "
            f"got status={step.status!r}"
        )
