"""Tests for UnitOfWork event methods."""

from sqlalchemy.orm import Session

from saz.db.models import Event as DBEvent
from saz.db.unit_of_work import UnitOfWork
from saz.domain.event_schema import Event, EventType
from tests.conftest import seed_run


def test_emit_event_buffers(db_engine):
    """emit_event() buffers events without persisting."""
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            event = Event(
                event_type=EventType.RUN_STARTED,
                run_id="run_123",
                summary="Test",
            )

            uow.emit_event(event)

            # Event is buffered but not persisted yet
            assert len(uow.pending_events) == 1
            assert uow.pending_events[0].id == event.id

            # DB query shows nothing yet
            count = session.query(DBEvent).count()
            assert count == 0


def test_commit_persists_events(db_engine):
    seed_run(db_engine, "run_123", step_ids=["step_1"])
    """commit() persists buffered events and clears buffer."""
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
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
                    summary="Step started",
                ),
            ]

            for event in events:
                uow.emit_event(event)

            # Commit returns emitted events
            emitted = uow.commit()

            assert len(emitted) == 2
            assert emitted[0].event_type == EventType.RUN_STARTED
            assert emitted[1].event_type == EventType.STEP_STARTED

            # Buffer is cleared
            assert len(uow.pending_events) == 0

        # Events are persisted
        count = session.query(DBEvent).filter_by(run_id="run_123").count()
        assert count == 2


def test_rollback_clears_buffer(db_engine):
    """rollback() clears event buffer without persisting."""
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            event = Event(
                event_type=EventType.RUN_STARTED,
                run_id="run_123",
                summary="Test",
            )

            uow.emit_event(event)
            assert len(uow.pending_events) == 1

            # Rollback
            uow.rollback()

            # Buffer is cleared
            assert len(uow.pending_events) == 0

        # Nothing persisted
        count = session.query(DBEvent).count()
        assert count == 0


def test_multiple_commits(db_engine):
    seed_run(db_engine, "run_123", step_ids=["step_1"])
    """Multiple commits work correctly."""
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            # First batch
            uow.emit_event(
                Event(
                    event_type=EventType.RUN_STARTED,
                    run_id="run_123",
                    summary="Started",
                )
            )
            emitted1 = uow.commit()
            assert len(emitted1) == 1

            # Second batch
            uow.emit_event(
                Event(
                    event_type=EventType.STEP_STARTED,
                    run_id="run_123",
                    step_id="step_1",
                    summary="Step 1",
                )
            )
            uow.emit_event(
                Event(
                    event_type=EventType.STEP_COMPLETED,
                    run_id="run_123",
                    step_id="step_1",
                    summary="Step 1 done",
                )
            )
            emitted2 = uow.commit()
            assert len(emitted2) == 2

        # All events persisted
        count = session.query(DBEvent).filter_by(run_id="run_123").count()
        assert count == 3


def test_pending_events_snapshot(db_engine):
    """pending_events returns a copy, not reference."""
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            event = Event(
                event_type=EventType.RUN_STARTED,
                run_id="run_123",
                summary="Test",
            )

            uow.emit_event(event)

            # Get snapshot
            snapshot = uow.pending_events
            assert len(snapshot) == 1

            # Modifying snapshot doesn't affect buffer
            snapshot.clear()
            assert len(uow.pending_events) == 1
