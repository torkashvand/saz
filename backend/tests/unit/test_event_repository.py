"""Tests for EventRepository write operations."""

from datetime import datetime

from sqlalchemy.orm import Session

from saz.db.models import Event as DBEvent
from saz.domain.event_schema import Event, EventType
from saz.repositories.write.event_repository import EventRepository


def test_event_repository_add(db_engine):
    """EventRepository.add() persists a single event."""
    with Session(db_engine) as session:
        repo = EventRepository(session)

        event = Event(
            event_type=EventType.RUN_STARTED,
            run_id="run_123",
            summary="Test run started",
            payload={"flow_id": "flow_1"},
        )

        repo.add(event)
        session.commit()

        # Verify persisted
        db_event = session.query(DBEvent).filter_by(id=event.id).first()
        assert db_event is not None
        assert db_event.event_type == "run.started"
        assert db_event.run_id == "run_123"
        assert db_event.summary == "Test run started"
        assert db_event.payload == {"flow_id": "flow_1"}


def test_event_repository_add_batch(db_engine):
    """EventRepository.add_batch() persists multiple events."""
    with Session(db_engine) as session:
        repo = EventRepository(session)

        events = [
            Event(
                event_type=EventType.RUN_STARTED,
                run_id="run_123",
                summary="Run started",
            ),
            Event(
                event_type=EventType.STEP_STARTED,
                run_id="run_123",
                step_id="step_1",
                summary="Step 1 started",
            ),
            Event(
                event_type=EventType.STEP_COMPLETED,
                run_id="run_123",
                step_id="step_1",
                summary="Step 1 completed",
            ),
        ]

        repo.add_batch(events)
        session.commit()

        # Verify all persisted
        db_events = session.query(DBEvent).filter_by(run_id="run_123").all()
        assert len(db_events) == 3

        event_types = [e.event_type for e in db_events]
        assert "run.started" in event_types
        assert "step.started" in event_types
        assert "step.completed" in event_types


def test_event_repository_preserves_all_fields(db_engine):
    """EventRepository preserves all event fields."""
    with Session(db_engine) as session:
        repo = EventRepository(session)

        now = datetime(2025, 1, 1, 12, 0, 0)
        event = Event(
            id="evt_custom123",
            event_type=EventType.TOOL_FAILED,
            timestamp=now,
            run_id="run_123",
            step_id="step_456",
            correlation_id="corr_789",
            planner_mode="agentic",
            severity="error",
            actor="llm",
            summary="Tool failed",
            payload={"error": "timeout", "duration_ms": 5000},
            tags={"tool": "http_request", "retry": "3"},
            schema_version=1,
        )

        repo.add(event)
        session.commit()

        # Read back
        db_event = session.query(DBEvent).filter_by(id="evt_custom123").first()

        assert db_event.id == "evt_custom123"
        assert db_event.event_type == "tool.failed"
        assert db_event.timestamp == now
        assert db_event.run_id == "run_123"
        assert db_event.step_id == "step_456"
        assert db_event.correlation_id == "corr_789"
        assert db_event.planner_mode == "agentic"
        assert db_event.severity == "error"
        assert db_event.actor == "llm"
        assert db_event.summary == "Tool failed"
        assert db_event.payload == {"error": "timeout", "duration_ms": 5000}
        assert db_event.tags == {"tool": "http_request", "retry": "3"}


def test_event_repository_add_batch_empty(db_engine):
    """EventRepository.add_batch() handles empty list."""
    with Session(db_engine) as session:
        repo = EventRepository(session)

        repo.add_batch([])
        session.commit()

        # No error, no events
        count = session.query(DBEvent).count()
        assert count == 0
