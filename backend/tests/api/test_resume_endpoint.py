"""Tests for resume endpoint (human approval workflow)."""

import pytest
from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step


@pytest.fixture
def suspended_run_with_approval(db_engine):
    """Create a suspended run awaiting human approval."""
    with Session(db_engine) as session:
        # Create flow with human.approval step
        flow = Flow(
            id="flow_approval_1",
            name="Approval Test Flow",
            definition={
                "schema_version": 1,
                "flow": {
                    "name": "Approval Test Flow",
                    "description": "Test workflow with human approval",
                },
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "extract_data",
                            "type": "ai.extract",
                            "instruction": "Extract data from input",
                        },
                        {
                            "id": "approve_decision",
                            "type": "human.approval",
                            "description": "Review and approve the decision",
                        },
                        {
                            "id": "execute_action",
                            "type": "tool.call",
                            "tool": "http_request",
                            "params": {"url": "https://example.com"},
                        },
                    ],
                },
            },
        )
        session.add(flow)
        session.commit()

        # Create run
        run = Run(
            id="run_suspended_1",
            flow_id="flow_approval_1",
            status="suspended",
            planner_mode="deterministic",
            payload={"request_id": "REQ-001"},
            error={
                "message": "Human approval required for step approve_decision",
                "type": "HumanApprovalRequired",
                "step_id": "approve_decision",
                "reasoning": "Review decision before executing action",
            },
        )
        session.add(run)
        session.commit()

        # Create steps
        step1 = Step(
            id="step_1",
            run_id="run_suspended_1",
            number=0,
            name="extract_data",
            step_type="ai.extract",
            status="completed",
            output={"extracted_field": "value123"},
        )
        step2 = Step(
            id="step_2",
            run_id="run_suspended_1",
            number=1,
            name="approve_decision",
            step_type="human.approval",
            status="suspended",
            output=None,  # Will be populated by resume
        )
        session.add_all([step1, step2])
        session.commit()

    return "run_suspended_1"


@pytest.fixture
def completed_run(db_engine):
    """Create a completed run (not resumable)."""
    with Session(db_engine) as session:
        flow = Flow(
            id="flow_completed",
            name="Completed Flow",
            definition={"workflow": {"planner_mode": "deterministic"}},
        )
        session.add(flow)

        run = Run(
            id="run_completed_1",
            flow_id="flow_completed",
            status="completed",
            planner_mode="deterministic",
            payload={"test": "data"},
        )
        session.add(run)
        session.commit()

    return "run_completed_1"


def test_resume_suspended_run_success(app_client, suspended_run_with_approval, db_engine):
    """POST /api/v1/runs/{id}/resume successfully resumes a suspended run."""
    resume_data = {
        "approved": True,
        "approver": "john.doe@example.com",
        "comments": "Approved for execution",
    }

    response = app_client.post(
        "/api/v1/runs/run_suspended_1/resume",
        json={"resume_data": resume_data},
    )

    assert response.status_code == 200

    data = response.json()
    assert data["run_id"] == "run_suspended_1"
    assert data["status"] == "queued"

    # Verify run status changed in database
    with Session(db_engine) as session:
        run = session.get(Run, "run_suspended_1")
        assert run is not None
        assert run.status == "queued"
        assert run.error is None  # Suspension error cleared

        # Verify suspended step now has output
        step = session.get(Step, "step_2")
        assert step is not None
        assert step.status == "completed"
        assert step.output == resume_data


def test_resume_with_override_payload(app_client, suspended_run_with_approval, db_engine):
    """POST /api/v1/runs/{id}/resume can override payload."""
    resume_data = {"approved": True}
    override_payload = {"additional_context": "urgent"}

    response = app_client.post(
        "/api/v1/runs/run_suspended_1/resume",
        json={
            "resume_data": resume_data,
            "override_payload": override_payload,
        },
    )

    assert response.status_code == 200

    # Verify payload updated
    with Session(db_engine) as session:
        run = session.get(Run, "run_suspended_1")
        assert run is not None
        assert run.payload["request_id"] == "REQ-001"  # Original preserved
        assert run.payload["additional_context"] == "urgent"  # Override added


def test_resume_run_not_found(app_client):
    """POST /api/v1/runs/{id}/resume returns 404 if run doesn't exist."""
    response = app_client.post(
        "/api/v1/runs/nonexistent_run/resume",
        json={"resume_data": {"approved": True}},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_resume_run_not_suspended(app_client, completed_run):
    """POST /api/v1/runs/{id}/resume returns 400 if run is not suspended."""
    response = app_client.post(
        "/api/v1/runs/run_completed_1/resume",
        json={"resume_data": {"approved": True}},
    )

    assert response.status_code == 400
    assert "not suspended" in response.json()["detail"].lower()


def test_resume_with_empty_resume_data(app_client, suspended_run_with_approval, db_engine):
    """POST /api/v1/runs/{id}/resume accepts empty resume_data."""
    response = app_client.post(
        "/api/v1/runs/run_suspended_1/resume",
        json={"resume_data": None},
    )

    assert response.status_code == 200

    # Run should be re-queued (or already running if scheduler picked it up)
    with Session(db_engine) as session:
        run = session.get(Run, "run_suspended_1")
        assert run.status in ["queued", "running", "failed", "completed"]
        # Main point: it's no longer suspended
        assert run.status != "suspended"


def test_resume_with_denial(app_client, suspended_run_with_approval, db_engine):
    """POST /api/v1/runs/{id}/resume can store denial decision."""
    resume_data = {
        "approved": False,
        "approver": "jane.smith@example.com",
        "reason": "Budget not approved",
    }

    response = app_client.post(
        "/api/v1/runs/run_suspended_1/resume",
        json={"resume_data": resume_data},
    )

    assert response.status_code == 200

    # Verify denial stored in step output
    with Session(db_engine) as session:
        step = session.get(Step, "step_2")
        assert step.output["approved"] is False
        assert step.output["reason"] == "Budget not approved"


def test_resume_minimal_request(app_client, suspended_run_with_approval):
    """POST /api/v1/runs/{id}/resume works with minimal request."""
    response = app_client.post(
        "/api/v1/runs/run_suspended_1/resume",
        json={},  # Empty body
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_resume_with_complex_resume_data(app_client, suspended_run_with_approval, db_engine):
    """POST /api/v1/runs/{id}/resume handles complex nested resume_data."""
    resume_data = {
        "approved": True,
        "approver": {
            "user_id": "U123",
            "email": "approver@example.com",
            "role": "manager",
        },
        "approval_metadata": {
            "timestamp": "2025-01-15T10:30:00Z",
            "ip_address": "192.168.1.100",
            "conditions": ["budget_ok", "security_reviewed"],
        },
    }

    response = app_client.post(
        "/api/v1/runs/run_suspended_1/resume",
        json={"resume_data": resume_data},
    )

    assert response.status_code == 200

    # Verify complex structure preserved
    with Session(db_engine) as session:
        step = session.get(Step, "step_2")
        assert step.output["approver"]["email"] == "approver@example.com"
        assert "security_reviewed" in step.output["approval_metadata"]["conditions"]


def test_resume_invalid_json(app_client, suspended_run_with_approval):
    """POST /api/v1/runs/{id}/resume rejects invalid JSON."""
    response = app_client.post(
        "/api/v1/runs/run_suspended_1/resume",
        data="not valid json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422  # FastAPI validation error
