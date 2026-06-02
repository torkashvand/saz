"""Write-side repository for audit events."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from saz.db.models import Event as DBEvent
from saz.domain.event_schema import Event as EventSchema


class EventRepository:
    """Write-side repository for audit events."""

    def __init__(self, session: Session):
        self.session = session

    def _max_seq(self, run_id: str) -> int:
        """Highest persisted seq for a run, or 0 if none yet."""
        return (
            self.session.query(func.max(DBEvent.seq)).filter(DBEvent.run_id == run_id).scalar() or 0
        )

    def add(self, event: EventSchema) -> None:
        """
        Add a single event to the session (not yet committed).

        Assigns a monotonic per-run ``seq`` so the event stream has a
        deterministic order even when timestamps collide. The domain object is
        mutated in place so the broadcast copy carries the same seq.
        """
        if event.seq is None:
            event.seq = self._max_seq(event.run_id) + 1
        self.session.add(self._to_db(event))

    def add_batch(self, events: list[EventSchema]) -> None:
        """
        Batch insert events for performance.

        Each event is assigned a monotonic per-run ``seq`` (continuing from the
        highest already persisted for that run). The domain objects are mutated
        in place so the returned/broadcast copies carry their seq.
        """
        if not events:
            return

        # Seed the next seq per run once, then increment locally for the batch.
        next_seq: dict[str, int] = {}
        for e in events:
            if e.seq is not None:
                continue
            if e.run_id not in next_seq:
                next_seq[e.run_id] = self._max_seq(e.run_id) + 1
            e.seq = next_seq[e.run_id]
            next_seq[e.run_id] += 1

        self.session.bulk_save_objects([self._to_db(e) for e in events])

    @staticmethod
    def _to_db(event: EventSchema) -> DBEvent:
        return DBEvent(
            id=event.id,
            event_type=event.event_type.value,
            timestamp=event.timestamp,
            schema_version=event.schema_version,
            seq=event.seq,
            run_id=event.run_id,
            step_id=event.step_id,
            correlation_id=event.correlation_id,
            planner_mode=event.planner_mode,
            severity=event.severity,
            actor=event.actor,
            actor_user_id=event.actor_user_id,
            summary=event.summary,
            payload=event.payload,
            tags=event.tags,
        )
