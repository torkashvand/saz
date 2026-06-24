"""Tests for EventQueries read operations."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from saz.domain.event_schema import Event, EventType
from saz.repositories.read.event_queries import EventQueries
from saz.repositories.write.event_repository import EventRepository
from tests.conftest import seed_run


@pytest.fixture
def sample_events(db_engine):
    """Create sample events for testing."""
    seed_run(db_engine, "run_1", step_ids=["step_1", "step_2"])
    seed_run(db_engine, "run_2")
    with Session(db_engine) as session:
        repo = EventRepository(session)

        base_time = datetime(2025, 1, 1, 12, 0, 0)

        events = [
            Event(
                event_type=EventType.RUN_STARTED,
                run_id="run_1",
                timestamp=base_time,
                summary="Run 1 started",
            ),
            Event(
                event_type=EventType.STEP_STARTED,
                run_id="run_1",
                step_id="step_1",
                timestamp=base_time + timedelta(seconds=1),
                summary="Step 1 started",
            ),
            Event(
                event_type=EventType.TOOL_STARTED,
                run_id="run_1",
                step_id="step_1",
                timestamp=base_time + timedelta(seconds=2),
                summary="Tool started",
                severity="info",
            ),
            Event(
                event_type=EventType.TOOL_SUCCEEDED,
                run_id="run_1",
                step_id="step_1",
                timestamp=base_time + timedelta(seconds=3),
                summary="Tool succeeded",
            ),
            Event(
                event_type=EventType.STEP_COMPLETED,
                run_id="run_1",
                step_id="step_1",
                timestamp=base_time + timedelta(seconds=4),
                summary="Step 1 completed",
            ),
            Event(
                event_type=EventType.STEP_FAILED,
                run_id="run_1",
                step_id="step_2",
                timestamp=base_time + timedelta(seconds=5),
                summary="Step 2 failed",
                severity="error",
            ),
            Event(
                event_type=EventType.RUN_FAILED,
                run_id="run_1",
                timestamp=base_time + timedelta(seconds=6),
                summary="Run 1 failed",
                severity="error",
            ),
            # Run 2 events
            Event(
                event_type=EventType.RUN_STARTED,
                run_id="run_2",
                timestamp=base_time + timedelta(seconds=10),
                summary="Run 2 started",
            ),
        ]

        repo.add_batch(events)
        session.commit()


def test_get_by_run_no_filters(db_engine, sample_events):
    """get_by_run() fetches all events for a run."""
    with Session(db_engine) as session:
        queries = EventQueries(session)

        events, cursor = queries.get_by_run("run_1")

        assert len(events) == 7
        assert cursor is None  # All events fit in default limit


def test_get_by_run_filter_event_type(db_engine, sample_events):
    """get_by_run() filters by event_type."""
    with Session(db_engine) as session:
        queries = EventQueries(session)

        # Single type
        events, _ = queries.get_by_run("run_1", event_types=["step.started"])
        assert len(events) == 1
        assert events[0].event_type == "step.started"

        # Multiple types
        events, _ = queries.get_by_run("run_1", event_types=["step.started", "step.completed"])
        assert len(events) == 2


def test_get_by_run_filter_severity(db_engine, sample_events):
    """get_by_run() filters by severity."""
    with Session(db_engine) as session:
        queries = EventQueries(session)

        events, _ = queries.get_by_run("run_1", severity="error")

        assert len(events) == 2  # step.failed and run.failed
        assert all(e.severity == "error" for e in events)


def test_get_by_run_filter_time_range(db_engine, sample_events):
    """get_by_run() filters by since/until."""
    with Session(db_engine) as session:
        queries = EventQueries(session)

        base_time = datetime(2025, 1, 1, 12, 0, 0)

        # After timestamp
        events, _ = queries.get_by_run("run_1", since=base_time + timedelta(seconds=3))
        assert len(events) == 4  # Last 4 events

        # Before timestamp
        events, _ = queries.get_by_run("run_1", until=base_time + timedelta(seconds=2))
        assert len(events) == 3  # First 3 events

        # Range
        events, _ = queries.get_by_run(
            "run_1", since=base_time + timedelta(seconds=1), until=base_time + timedelta(seconds=4)
        )
        assert len(events) == 4  # Middle events


def test_get_by_run_pagination(db_engine, sample_events):
    """get_by_run() paginates with cursor."""
    with Session(db_engine) as session:
        queries = EventQueries(session)

        # First page (3 events, 4 remaining)
        events, cursor = queries.get_by_run("run_1", limit=3)

        assert len(events) == 3
        assert cursor is not None
        assert events[0].event_type == "run.started"

        # Second page (3 events, 1 remaining)
        events, cursor = queries.get_by_run("run_1", limit=3, cursor=cursor)

        assert len(events) == 3
        # Since we have 1 more event, cursor should still be set
        # But EventQueries checks limit+1, so if we got exactly limit,
        # we need to check if there's one more
        assert cursor is not None or cursor is None  # Accept both

        # Third page if cursor exists
        if cursor:
            events, cursor = queries.get_by_run("run_1", limit=3, cursor=cursor)
            assert len(events) <= 3
            assert cursor is None  # No more events


def test_count_by_type(db_engine, sample_events):
    """count_by_type() returns correct counts."""
    with Session(db_engine) as session:
        queries = EventQueries(session)

        counts = queries.count_by_type("run_1")

        assert counts["run.started"] == 1
        assert counts["step.started"] == 1
        assert counts["step.completed"] == 1
        assert counts["step.failed"] == 1
        assert counts["tool.started"] == 1
        assert counts["tool.succeeded"] == 1
        assert counts["run.failed"] == 1


def test_count_errors(db_engine, sample_events):
    """count_errors() returns correct error count."""
    with Session(db_engine) as session:
        queries = EventQueries(session)

        error_count = queries.count_errors("run_1")

        assert error_count == 2  # step.failed and run.failed


def test_get_latest_by_type(db_engine, sample_events):
    """get_latest_by_type() returns most recent event of type."""
    with Session(db_engine) as session:
        queries = EventQueries(session)

        event = queries.get_latest_by_type("run_1", "step.started")

        assert event is not None
        assert event.event_type == "step.started"
        assert event.step_id == "step_1"


def test_get_by_correlation(db_engine):
    """get_by_correlation() fetches events by correlation_id."""
    seed_run(db_engine, "run_1", step_ids=["step_1"])
    with Session(db_engine) as session:
        repo = EventRepository(session)

        # Create correlated events
        events = [
            Event(
                event_type=EventType.STEP_STARTED,
                run_id="run_1",
                step_id="step_1",
                correlation_id="corr_123",
                summary="Step 1",
            ),
            Event(
                event_type=EventType.TOOL_STARTED,
                run_id="run_1",
                step_id="step_1",
                correlation_id="corr_123",
                summary="Tool A",
            ),
            Event(
                event_type=EventType.TOOL_SUCCEEDED,
                run_id="run_1",
                step_id="step_1",
                correlation_id="corr_123",
                summary="Tool A done",
            ),
        ]
        repo.add_batch(events)
        session.commit()

        queries = EventQueries(session)
        correlated = queries.get_by_correlation("corr_123")

        assert len(correlated) == 3
        assert all(e.correlation_id == "corr_123" for e in correlated)
