"""Write-side repository for audit events."""

from sqlalchemy.orm import Session

from saz.db.models import Event as DBEvent
from saz.domain.event_schema import Event as EventSchema


class EventRepository:
    """Write-side repository for audit events."""

    def __init__(self, session: Session):
        self.session = session

    def add(self, event: EventSchema) -> None:
        """
        Add a single event to the session (not yet committed).

        Args:
            event: Event domain object to persist
        """
        db_event = DBEvent(
            id=event.id,
            event_type=event.event_type.value,
            timestamp=event.timestamp,
            schema_version=event.schema_version,
            run_id=event.run_id,
            step_id=event.step_id,
            correlation_id=event.correlation_id,
            planner_mode=event.planner_mode,
            severity=event.severity,
            actor=event.actor,
            summary=event.summary,
            payload=event.payload,
            tags=event.tags,
        )
        self.session.add(db_event)

    def add_batch(self, events: list[EventSchema]) -> None:
        """
        Batch insert events for performance.

        Args:
            events: List of event domain objects to persist
        """
        if not events:
            return

        db_events = [
            DBEvent(
                id=e.id,
                event_type=e.event_type.value,
                timestamp=e.timestamp,
                schema_version=e.schema_version,
                run_id=e.run_id,
                step_id=e.step_id,
                correlation_id=e.correlation_id,
                planner_mode=e.planner_mode,
                severity=e.severity,
                actor=e.actor,
                summary=e.summary,
                payload=e.payload,
                tags=e.tags,
            )
            for e in events
        ]
        self.session.bulk_save_objects(db_events)
