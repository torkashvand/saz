"""Tests for runs API endpoints."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from saz.domain.event_schema import Event, EventType
from saz.repositories.write.event_repository import EventRepository


@pytest.fixture
def run_with_events(db_engine, app_client):
    """Create a run with events for testing."""
    with Session(db_engine) as session:
        # Create flow
        from saz.db.models import Flow, Run

        flow = Flow(
            id="flow_1",
            name="Test Flow",
            definition={"workflow": {"planner_mode": "deterministic"}},
        )
        session.add(flow)
        session.commit()

        # Create run
        run = Run(
            id="run_123",
            flow_id="flow_1",
            status="completed",
            planner_mode="deterministic",
            payload={"test": "data"},
            total_tokens=1000,
            total_cost_usd=0.05,
            duration_ms=5000,
        )
        session.add(run)
        session.commit()

        # Create events
        repo = EventRepository(session)
        base_time = datetime(2025, 1, 1, 12, 0, 0)

        events = [
            Event(
                event_type=EventType.RUN_STARTED,
                run_id="run_123",
                timestamp=base_time,
                summary="Run started",
            ),
            Event(
                event_type=EventType.STEP_STARTED,
                run_id="run_123",
                step_id="step_1",
                timestamp=base_time + timedelta(seconds=1),
                summary="Step 1 started",
            ),
            Event(
                event_type=EventType.TOOL_STARTED,
                run_id="run_123",
                step_id="step_1",
                timestamp=base_time + timedelta(seconds=2),
                summary="Tool started",
            ),
            Event(
                event_type=EventType.TOOL_SUCCEEDED,
                run_id="run_123",
                step_id="step_1",
                timestamp=base_time + timedelta(seconds=3),
                summary="Tool succeeded",
            ),
            Event(
                event_type=EventType.STEP_COMPLETED,
                run_id="run_123",
                step_id="step_1",
                timestamp=base_time + timedelta(seconds=4),
                summary="Step 1 completed",
            ),
            Event(
                event_type=EventType.RUN_COMPLETED,
                run_id="run_123",
                timestamp=base_time + timedelta(seconds=5),
                summary="Run completed",
            ),
            # Add an error event
            Event(
                event_type=EventType.SYSTEM_WARNING,
                run_id="run_123",
                timestamp=base_time + timedelta(seconds=6),
                summary="Warning occurred",
                severity="error",
            ),
        ]

        repo.add_batch(events)
        session.commit()

    return "run_123"


def test_get_run_summary_success(app_client, run_with_events):
    """GET /api/v1/runs/{id} returns run detail with steps."""
    response = app_client.get("/api/v1/runs/run_123")

    assert response.status_code == 200

    data = response.json()
    assert data["id"] == "run_123"
    assert data["flow_id"] == "flow_1"
    assert data["status"] == "completed"
    assert data["planner_mode"] == "deterministic"
    assert data["total_tokens"] == 1000
    assert data["total_cost_usd"] == 0.05
    assert data["duration_ms"] == 5000

    # Check that steps array is present (RunDetailResponse)
    assert "steps" in data
    assert isinstance(data["steps"], list)

    # Check that flow_name is present
    assert "flow_name" in data
    assert isinstance(data["flow_name"], str)


def test_get_run_summary_not_found(app_client):
    """GET /api/v1/runs/{id} returns 404 for unknown run."""
    response = app_client.get("/api/v1/runs/nonexistent")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_run_events_all(app_client, run_with_events):
    """GET /api/v1/runs/{id}/events returns all events."""
    response = app_client.get("/api/v1/runs/run_123/events")

    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 7
    assert data["has_more"] is False
    assert data["cursor"] is None

    events = data["events"]
    assert len(events) == 7

    # Events are ordered by timestamp
    assert events[0]["event_type"] == "run.started"
    assert events[-1]["event_type"] == "system.warning"


def test_get_run_events_filter_event_type(app_client, run_with_events):
    """GET /api/v1/runs/{id}/events filters by event_type."""
    response = app_client.get(
        "/api/v1/runs/run_123/events",
        params={"event_type": ["step.started", "step.completed"]},
    )

    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 2

    events = data["events"]
    event_types = [e["event_type"] for e in events]
    assert "step.started" in event_types
    assert "step.completed" in event_types


def test_get_run_events_filter_severity(app_client, run_with_events):
    """GET /api/v1/runs/{id}/events filters by severity."""
    response = app_client.get(
        "/api/v1/runs/run_123/events",
        params={"severity": "error"},
    )

    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1

    event = data["events"][0]
    assert event["severity"] == "error"


def test_get_run_events_pagination(app_client, run_with_events):
    """GET /api/v1/runs/{id}/events paginates with cursor."""
    # First page
    response = app_client.get(
        "/api/v1/runs/run_123/events",
        params={"limit": 3},
    )

    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 3
    assert data["has_more"] is True
    assert data["cursor"] is not None

    # Second page - verify cursor-based pagination works
    cursor = data["cursor"]
    response = app_client.get(
        "/api/v1/runs/run_123/events",
        params={"limit": 3, "cursor": cursor},
    )

    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 3
    # Cursor pagination working correctly
    assert len(data["events"]) == 3


def test_get_run_events_time_range(app_client, run_with_events):
    """GET /api/v1/runs/{id}/events filters by time range."""
    base_time = datetime(2025, 1, 1, 12, 0, 0)

    # After timestamp
    response = app_client.get(
        "/api/v1/runs/run_123/events",
        params={"since": (base_time + timedelta(seconds=3)).isoformat()},
    )

    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 4  # Last 4 events


def test_get_run_events_not_found(app_client):
    """GET /api/v1/runs/{id}/events returns 404 for unknown run."""
    response = app_client.get("/api/v1/runs/nonexistent/events")

    assert response.status_code == 404
