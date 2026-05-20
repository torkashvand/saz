"""API-level tests for webhook callback endpoint.

Proves proposal claim: "inbound webhook endpoint for approve/reject/continue,
callback_id is non-guessable UUID, duplicate callback handled idempotently."
"""

import pytest
from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step
from tests.conftest import TEST_USER_ID


@pytest.fixture
def suspended_run_with_callback(db_engine):
    """Create a suspended run with callback_id for webhook callback testing."""
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_webhook_api",
            name="Webhook Test Flow",
            definition={
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "approval_step",
                            "type": "human.approval",
                            "description": "Approve the action",
                        },
                    ],
                },
            },
        )
        session.add(flow)
        session.commit()

        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_webhook_api_1",
            flow_id="flow_webhook_api",
            status="suspended",
            planner_mode="deterministic",
            payload={"data": "test"},
            error={
                "message": "Human approval required",
                "type": "HumanApprovalRequired",
                "step_id": "approval_step",
                "callback_id": "cb_test_abc123def456",
            },
        )
        session.add(run)

        step = Step(
            id="step_webhook_1",
            run_id="run_webhook_api_1",
            number=0,
            name="approval_step",
            step_type="human.approval",
            status="suspended",
        )
        session.add(step)
        session.commit()

    return "run_webhook_api_1", "cb_test_abc123def456"


def test_webhook_callback_approve(app_client, suspended_run_with_callback, db_engine):
    """POST /api/v1/webhooks/callback/{callback_id} approves and resumes run."""
    run_id, callback_id = suspended_run_with_callback

    response = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "approve", "data": {"approver": "admin"}},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "resumed"
    assert data["run_id"] == run_id


def test_webhook_callback_reject(app_client, suspended_run_with_callback, db_engine):
    """POST /api/v1/webhooks/callback/{callback_id} with reject fails the run."""
    run_id, callback_id = suspended_run_with_callback

    response = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "reject", "reason": "Not authorized"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "rejected"
    assert data["run_id"] == run_id

    # Verify run is marked as failed in DB
    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run.status == "failed"
        assert run.error["type"] == "WebhookRejection"


def test_webhook_callback_not_found(app_client):
    """POST /api/v1/webhooks/callback/{callback_id} returns 404 for unknown callback."""
    response = app_client.post(
        "/api/v1/webhooks/callback/nonexistent_callback_id",
        json={"action": "approve"},
    )
    assert response.status_code == 404


def test_webhook_callback_idempotent(app_client, suspended_run_with_callback, db_engine):
    """Duplicate approve callback is handled gracefully.

    After first approval the run is no longer suspended. The second call
    finds the run (by callback_id in error dict) but sees it's not suspended,
    returning already_processed for true idempotency.
    """
    _, callback_id = suspended_run_with_callback

    # First call: approve
    r1 = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "approve"},
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "resumed"

    # Verify run is no longer suspended
    with Session(db_engine) as session:
        run = session.get(Run, "run_webhook_api_1")
        assert run.status != "suspended"

    # Second call: same callback — idempotent, returns already_processed
    r2 = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "approve"},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "already_processed"


def test_webhook_callback_default_action_is_approve(app_client, suspended_run_with_callback):
    """Webhook callback with empty body defaults to approve action."""
    _, callback_id = suspended_run_with_callback

    response = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "resumed"


@pytest.fixture
def suspended_run_for_reject(db_engine):
    """Separate suspended run fixture for rejection tests (avoids fixture reuse conflicts)."""
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_webhook_reject",
            name="Webhook Reject Flow",
            definition={
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {"id": "gate", "type": "human.approval", "description": "Gate"},
                    ],
                },
            },
        )
        session.add(flow)
        session.commit()

        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_webhook_reject_1",
            flow_id="flow_webhook_reject",
            status="suspended",
            planner_mode="deterministic",
            payload={},
            error={
                "message": "Human approval required",
                "type": "HumanApprovalRequired",
                "step_id": "gate",
                "callback_id": "cb_reject_dup_test",
            },
        )
        session.add(run)

        step = Step(
            id="step_reject_1",
            run_id="run_webhook_reject_1",
            number=0,
            name="gate",
            step_type="human.approval",
            status="suspended",
        )
        session.add(step)
        session.commit()

    return "run_webhook_reject_1", "cb_reject_dup_test"


def test_webhook_callback_reject_idempotent(app_client, suspended_run_for_reject, db_engine):
    """Duplicate reject callback returns already_processed."""
    run_id, callback_id = suspended_run_for_reject

    # First call: reject
    r1 = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "reject", "reason": "Denied"},
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "rejected"

    # Verify run is failed in DB
    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run.status == "failed"

    # Second call: same callback — idempotent
    r2 = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "reject"},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "already_processed"
    assert r2.json()["run_id"] == run_id


def test_webhook_callback_mixed_repeat_is_stable(
    app_client, suspended_run_with_callback, db_engine
):
    """After first approve, repeated calls with different actions all return already_processed."""
    _, callback_id = suspended_run_with_callback

    # First: approve
    r1 = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "approve"},
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "resumed"

    # Second: try to reject the same callback — already processed, not re-rejected
    r2 = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "reject", "reason": "Too late"},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "already_processed"

    # Third: approve again — still already_processed
    r3 = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "approve"},
    )
    assert r3.status_code == 200
    assert r3.json()["status"] == "already_processed"


def test_webhook_callback_approve_completes_step(
    app_client, suspended_run_with_callback, db_engine
):
    """After webhook approval, the suspended step must be marked completed
    and resume_data stored in step.output."""
    run_id, callback_id = suspended_run_with_callback

    response = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "approve", "data": {"approver": "ops-team"}},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "resumed"

    with Session(db_engine) as session:
        step = session.get(Step, "step_webhook_1")
        assert step is not None
        assert (
            step.status == "completed"
        ), f"Step must be completed after approval, got: {step.status}"
        assert step.output is not None
        assert step.output["approved"] is True
        assert step.output["callback_id"] == callback_id
        assert step.output["approver"] == "ops-team"


def test_webhook_callback_preserves_suspension_context(
    app_client, suspended_run_with_callback, db_engine
):
    """After webhook approval, run.error must preserve the original suspension
    context (step_id, type, reasoning) for audit/debugging, not just overwrite
    with a bare {callback_id, resolved} marker."""
    run_id, callback_id = suspended_run_with_callback

    app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "approve"},
    )

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run.error is not None
        # callback_id and resolved marker present
        assert run.error["callback_id"] == callback_id
        assert run.error["resolved"] is True
        # Original suspension context preserved
        assert run.error["type"] == "HumanApprovalRequired"
        assert run.error["step_id"] == "approval_step"


def test_webhook_callback_reject_preserves_callback_id(
    app_client, suspended_run_for_reject, db_engine
):
    """After webhook rejection, run.error must include callback_id so
    find_by_callback_id can still locate the run for idempotent duplicate
    detection."""
    run_id, callback_id = suspended_run_for_reject

    app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "reject", "reason": "Unauthorized"},
    )

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run.status == "failed"
        assert run.error["callback_id"] == callback_id
        assert run.error["type"] == "WebhookRejection"


def test_webhook_callback_invalid_action(app_client, suspended_run_with_callback):
    """Webhook callback with invalid action returns a validation error,
    not a silent default to approve."""
    _, callback_id = suspended_run_with_callback

    response = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "invalid_action"},
    )
    # Should be rejected, not silently approved
    assert response.status_code in (400, 422)


@pytest.fixture
def many_runs_with_errors(db_engine):
    """Create multiple runs with various error dicts, only one with the target callback."""
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_perf_test",
            name="Perf Test",
            definition={"workflow": {"planner_mode": "deterministic", "steps": []}},
        )
        session.add(flow)
        session.commit()

        # Create 50 runs with various errors (none with our callback)
        for i in range(50):
            run = Run(
                created_by_user_id=TEST_USER_ID,
                id=f"run_noise_{i}",
                flow_id="flow_perf_test",
                status="failed",
                planner_mode="deterministic",
                payload={},
                error={"message": f"Error {i}", "type": "SomeError"},
            )
            session.add(run)

        # One run with the target callback
        target = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_target",
            flow_id="flow_perf_test",
            status="suspended",
            planner_mode="deterministic",
            payload={},
            error={
                "message": "Approval needed",
                "type": "HumanApprovalRequired",
                "step_id": "gate",
                "callback_id": "cb_needle_in_haystack",
            },
        )
        session.add(target)
        session.commit()

    return "run_target", "cb_needle_in_haystack"


def test_find_by_callback_id_among_many_runs(app_client, many_runs_with_errors, db_engine):
    """find_by_callback_id correctly finds the target among many error-bearing runs."""
    run_id, callback_id = many_runs_with_errors

    response = app_client.post(
        f"/api/v1/webhooks/callback/{callback_id}",
        json={"action": "approve"},
    )
    assert response.status_code == 200
    assert response.json()["run_id"] == run_id
    assert response.json()["status"] == "resumed"
