"""Run list / summary / steps endpoints must sanitize errors like /runs/{id}.

Bug being pinned: routes/runs.py defines sanitize_error() and applies it in
get_run_detail() but NOT in list_runs(), get_run_summary(), or get_run_steps().
A run.error containing a traceback or other sensitive payload leaks via these
sibling endpoints even though detail strips it.
"""

import pytest
from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step

SENSITIVE_RUN_ERROR = {
    "type": "RuntimeError",
    "message": "boom",
    "traceback": (
        'Traceback (most recent call last):\n'
        '  File "saz/engine/executor.py", line 999, in execute_run\n'
        '    raise RuntimeError("boom")\n'
        "RuntimeError: boom"
    ),
    "stack_trace": "internal-stack-frame-1\ninternal-stack-frame-2",
}

SENSITIVE_STEP_ERROR = {
    "type": "ValueError",
    "message": "bad input",
    "traceback": "Traceback (most recent call last):\n  ...\nValueError: bad input",
}


@pytest.fixture
def failed_run_with_traceback(db_engine):
    with Session(db_engine) as session:
        flow = Flow(
            id="flow_sanitize",
            name="sanitize_test",
            definition={"workflow": {"planner_mode": "deterministic", "steps": []}},
        )
        session.add(flow)
        run = Run(
            id="run_sanitize_1",
            flow_id="flow_sanitize",
            status="failed",
            planner_mode="deterministic",
            payload={},
            error=SENSITIVE_RUN_ERROR,
        )
        session.add(run)

        step = Step(
            id="step_sanitize_1",
            run_id="run_sanitize_1",
            number=0,
            name="boom_step",
            step_type="tool.call",
            status="failed",
            attempt=1,
            error=SENSITIVE_STEP_ERROR,
        )
        session.add(step)
        session.commit()

    return "run_sanitize_1"


def _no_traceback(error: dict | None) -> bool:
    if not error:
        return True
    blob = str(error)
    return "Traceback" not in blob and "stack_trace" not in error


def test_run_list_does_not_leak_traceback(app_client, failed_run_with_traceback):
    response = app_client.get("/api/v1/runs", params={"limit": 100})
    assert response.status_code == 200, response.text

    items = response.json()["items"]
    target = next(item for item in items if item["id"] == failed_run_with_traceback)
    assert _no_traceback(target.get("error")), (
        "list_runs returns r.error raw — sanitize_error() must be applied here "
        f"the same way it is in get_run_detail. Leaked payload: {target.get('error')!r}"
    )


def test_run_summary_does_not_leak_traceback(app_client, failed_run_with_traceback):
    response = app_client.get(f"/api/v1/runs/{failed_run_with_traceback}/summary")
    assert response.status_code == 200, response.text

    error = response.json().get("error")
    assert _no_traceback(error), (
        "get_run_summary returns run.error raw — must call sanitize_error like "
        f"get_run_detail does. Leaked payload: {error!r}"
    )


def test_run_steps_does_not_leak_step_traceback(app_client, failed_run_with_traceback):
    response = app_client.get(f"/api/v1/runs/{failed_run_with_traceback}/steps")
    assert response.status_code == 200, response.text

    steps = response.json()["steps"]
    assert steps, "sanity: fixture has at least one step"
    step_error = steps[0].get("error")
    assert _no_traceback(step_error), (
        "get_run_steps returns s.error raw — get_run_detail wraps each step's "
        "error with sanitize_error(). The /steps endpoint must do the same. "
        f"Leaked payload: {step_error!r}"
    )
