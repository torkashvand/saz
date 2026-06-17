"""Integration tests for complete human approval workflow."""

import pytest
from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step
from tests.conftest import TEST_USER_ID


@pytest.fixture
def approval_workflow(db_engine):
    """Create approval workflow definition."""
    # Example workflow YAML structure (used as reference for flow definition below)
    # This demonstrates the DSL format but we create the flow directly in code for testing
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="approval_flow_1",
            name="Purchase Approval Workflow",
            definition={
                "schema_version": 1,
                "flow": {
                    "name": "Purchase Approval Workflow",
                    "description": "Workflow with human approval gate",
                },
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "extract_purchase_details",
                            "type": "ai.extract",
                            "instruction": "Extract purchase amount and vendor",
                        },
                        {
                            "id": "request_approval",
                            "type": "human.approval",
                            "description": "Review and approve purchase",
                        },
                        {
                            "id": "create_purchase_order",
                            "type": "tool.call",
                            "tool": "http_request",
                            "params": {
                                "method": "POST",
                                "url": "https://erp.example.com/api/po",
                            },
                        },
                    ],
                },
                "policies": {"budget_usd": 0.50},
            },
        )
        session.add(flow)
        session.commit()

    return "approval_flow_1"


def test_approval_workflow_suspend_and_resume(app_client, approval_workflow, db_engine):
    """Test full approval workflow: create, suspend, resume, complete."""

    # Step 1: Create run directly in database (API endpoint for creating runs tested elsewhere)
    run_id = "test_approval_run_1"

    with Session(db_engine) as session:
        # Create the run
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id=run_id,
            flow_id="approval_flow_1",
            status="suspended",
            planner_mode="deterministic",
            payload={"purchase_request": "Need to buy servers for $5000 from VendorCo"},
            error={
                "type": "HumanApprovalRequired",
                "step_id": "request_approval",
                "message": "Human approval required",
            },
        )
        session.add(run)

        # Create completed first step
        step1 = Step(
            id=f"{run_id}_step_1",
            run_id=run_id,
            number=0,
            name="extract_purchase_details",
            step_type="ai.extract",
            status="completed",
            output={"amount": 5000, "vendor": "VendorCo"},
        )

        # Create suspended approval step
        step2 = Step(
            id=f"{run_id}_step_2",
            run_id=run_id,
            number=1,
            name="request_approval",
            step_type="human.approval",
            status="suspended",
        )

        session.add_all([step1, step2])
        session.commit()

    # Step 2: Verify run is suspended
    response = app_client.get(f"/api/v1/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "suspended"

    # Step 3: Resume with approval
    approval_data = {
        "approved": True,
        "approver": "manager@example.com",
        "comments": "Approved - critical infrastructure upgrade",
        "approval_timestamp": "2025-01-15T14:30:00Z",
    }

    response = app_client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"resume_data": approval_data},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"

    # Step 4: Verify step output contains approval data
    with Session(db_engine) as session:
        step = session.get(Step, f"{run_id}_step_2")
        assert step.status == "completed"
        assert step.output["approved"] is True
        assert step.output["approver"] == "manager@example.com"

    # Step 5: Verify run can be retrieved with approval data
    response = app_client.get(f"/api/v1/runs/{run_id}")
    assert response.status_code == 200

    run_data = response.json()
    approval_step = next(s for s in run_data["steps"] if s["name"] == "request_approval")
    assert approval_step["output"]["approved"] is True


def test_approval_workflow_denial(app_client, approval_workflow, db_engine):
    """Test approval workflow with denial (rejected approval)."""

    # Create run directly
    run_id = "test_denial_run"

    with Session(db_engine) as session:
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id=run_id,
            flow_id="approval_flow_1",
            status="suspended",
            planner_mode="deterministic",
            payload={"purchase_request": "test"},
        )
        session.add(run)

        step = Step(
            id=f"{run_id}_approval",
            run_id=run_id,
            number=0,
            name="request_approval",
            step_type="human.approval",
            status="suspended",
        )
        session.add(step)
        session.commit()

    # Resume with denial
    denial_data = {
        "approved": False,
        "approver": "cfo@example.com",
        "reason": "Budget constraints - denied",
    }

    response = app_client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"resume_data": denial_data},
    )

    assert response.status_code == 200
    # Rejection must NOT resume the run — it stops it.
    assert response.json()["status"] == "rejected"

    # The run is failed and the approval step is failed (never completed), so
    # no later step can run.
    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run.status == "failed", f"rejected run must fail, got {run.status!r}"

        step = session.get(Step, f"{run_id}_approval")
        assert step.status == "failed", f"rejected gate must fail, got {step.status!r}"
        # The denial reason is preserved for the operator.
        assert step.output["approved"] is False
        assert "Budget constraints" in step.output["reason"]


def test_approval_workflow_context_restoration(app_client, approval_workflow, db_engine):
    """Test that context is restored when resuming (previous step outputs available)."""

    # Create run directly with multiple completed steps
    run_id = "test_context_run"

    with Session(db_engine) as session:
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id=run_id,
            flow_id="approval_flow_1",
            status="suspended",
            planner_mode="deterministic",
            payload={"test": "data"},
        )
        session.add(run)

        # Create multiple completed steps before approval
        step1 = Step(
            id=f"{run_id}_step_1",
            run_id=run_id,
            number=0,
            name="extract_purchase_details",
            step_type="ai.extract",
            status="completed",
            output={"amount": 3000, "vendor": "SupplierCo"},
        )

        step2 = Step(
            id=f"{run_id}_step_2",
            run_id=run_id,
            number=1,
            name="request_approval",
            step_type="human.approval",
            status="suspended",
        )

        session.add_all([step1, step2])
        session.commit()

    # Resume
    response = app_client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"resume_data": {"approved": True}},
    )

    assert response.status_code == 200

    # Verify previous step output is preserved and accessible
    response = app_client.get(f"/api/v1/runs/{run_id}")
    run_data = response.json()

    extract_step = next(s for s in run_data["steps"] if s["name"] == "extract_purchase_details")
    assert extract_step["output"]["amount"] == 3000
    assert extract_step["output"]["vendor"] == "SupplierCo"


def test_multiple_approvals_in_workflow(app_client, db_engine, monkeypatch):
    """Test workflow with multiple approval gates.

    The test simulates execution by hand (direct ORM inserts + manual
    status flips) and never actually wants the executor to run. We
    monkey-patch ``scheduler.schedule`` to a no-op so the background
    thread can't race with our manual state injection and overwrite the
    "suspended" status we set between the two /resume calls.
    """
    # Patch both call sites (resume + retry) so any background scheduling
    # the route does becomes a no-op while this test runs.
    monkeypatch.setattr(
        "saz.api.routes.webhooks.get_scheduler",
        lambda: type("FakeSched", (), {"schedule": lambda self, _rid: True})(),
    )

    # Create flow with two approval steps
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="multi_approval_flow",
            name="Multi Approval Flow",
            definition={
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {"id": "step1", "type": "ai.extract"},
                        {
                            "id": "approval1",
                            "type": "human.approval",
                            "description": "First approval",
                        },
                        {"id": "step2", "type": "ai.generate"},
                        {
                            "id": "approval2",
                            "type": "human.approval",
                            "description": "Second approval",
                        },
                    ],
                }
            },
        )
        session.add(flow)
        session.commit()

    # Create run directly
    run_id = "test_multi_approval_run"

    with Session(db_engine) as session:
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id=run_id,
            flow_id="multi_approval_flow",
            status="suspended",
            planner_mode="deterministic",
            payload={},
        )
        session.add(run)

        step1 = Step(
            id=f"{run_id}_approval1",
            run_id=run_id,
            number=1,
            name="approval1",
            step_type="human.approval",
            status="suspended",
        )
        session.add(step1)
        session.commit()

    # Resume first approval
    response = app_client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"resume_data": {"approved": True, "approver": "user1"}},
    )

    assert response.status_code == 200

    # Simulate execution to second approval
    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        run.status = "suspended"

        step2 = Step(
            id=f"{run_id}_approval2",
            run_id=run_id,
            number=3,
            name="approval2",
            step_type="human.approval",
            status="suspended",
        )
        session.add(step2)
        session.commit()

    # Resume second approval
    response = app_client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"resume_data": {"approved": True, "approver": "user2"}},
    )

    assert response.status_code == 200

    # Verify both approvals recorded
    response = app_client.get(f"/api/v1/runs/{run_id}")
    run_data = response.json()

    approval_steps = [s for s in run_data["steps"] if s["step_type"] == "human.approval"]
    assert len(approval_steps) == 2
    assert approval_steps[0]["output"]["approver"] == "user1"
    assert approval_steps[1]["output"]["approver"] == "user2"


def test_approval_with_timeout_simulation(app_client, approval_workflow, db_engine):
    """Test approval workflow with simulated timeout (future enhancement test)."""

    # Create suspended run directly
    run_id = "test_timeout_run"

    with Session(db_engine) as session:
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id=run_id,
            flow_id="approval_flow_1",
            status="suspended",
            planner_mode="deterministic",
            payload={},
        )
        session.add(run)

        step = Step(
            id=f"{run_id}_approval",
            run_id=run_id,
            number=0,
            name="request_approval",
            step_type="human.approval",
            status="suspended",
        )
        session.add(step)
        session.commit()

    # Note: Timeout handling not yet implemented
    # This test documents expected behavior for future enhancement

    # For now, verify run remains suspended indefinitely
    response = app_client.get(f"/api/v1/runs/{run_id}")
    assert response.json()["status"] == "suspended"

    # Future: After timeout, run should auto-fail or escalate
    # Expected: run.status == "failed" with timeout error
