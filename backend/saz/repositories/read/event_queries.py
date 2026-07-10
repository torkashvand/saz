"""Read-side queries for audit events."""

from datetime import datetime

from sqlalchemy import func, tuple_
from sqlalchemy.orm import Session

from saz.db.models import Event


class EventQueries:
    """Read-side queries for audit events."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_run(
        self,
        run_id: str,
        event_types: list[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        severity: str | None = None,
        limit: int = 100,
        cursor: str | None = None,  # "<ISO timestamp>|<seq>" from a previous page
    ) -> tuple[list[Event], str | None]:
        """
        Fetch events for a run with filtering and pagination.

        Args:
            run_id: Run ID to fetch events for
            event_types: Optional list of event type filters
            since: Optional start timestamp filter
            until: Optional end timestamp filter
            severity: Optional severity filter (info, warn, error)
            limit: Maximum number of events to return
            cursor: opaque cursor from a previous page ("<ISO timestamp>|<seq>")

        Returns:
            Tuple of (events list, next_cursor)
        """
        query = self.session.query(Event).filter(Event.run_id == run_id)

        # Apply filters
        if event_types:
            query = query.filter(Event.event_type.in_(event_types))
        if since:
            query = query.filter(Event.timestamp >= since)
        if until:
            query = query.filter(Event.timestamp <= until)
        if severity:
            query = query.filter(Event.severity == severity)

        # Cursor-based pagination: continue strictly after (timestamp, seq) of
        # the last event returned on the previous page. A timestamp-only
        # cursor would skip events sharing the boundary timestamp — the very
        # case seq exists for. Rows predating seq sort as -1.
        seq_order = func.coalesce(Event.seq, -1)
        if cursor:
            raw_ts, sep, raw_seq = cursor.partition("|")
            try:
                cursor_dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                cursor_seq = int(raw_seq) if sep else -1
            except ValueError:
                pass  # Invalid cursor, ignore
            else:
                query = query.filter(tuple_(Event.timestamp, seq_order) > (cursor_dt, cursor_seq))

        # Deterministic order: timestamp first (stable across rows written
        # before seq existed), then the monotonic per-run seq, then id as a
        # final tie-breaker. limit + 1 checks for a next page.
        query = query.order_by(Event.timestamp.asc(), seq_order.asc(), Event.id.asc()).limit(
            limit + 1
        )

        events = query.all()

        # Next cursor points at the last event actually returned, so the
        # strict > filter above resumes exactly one event later.
        next_cursor = None
        if len(events) > limit:
            events = events[:limit]
            last = events[-1]
            last_seq = last.seq if last.seq is not None else -1
            next_cursor = f"{last.timestamp.isoformat()}|{last_seq}"

        return events, next_cursor

    def count_by_type(self, run_id: str) -> dict[str, int]:
        """
        Get event counts grouped by type for a run.

        Args:
            run_id: Run ID to count events for

        Returns:
            Dictionary mapping event_type to count
        """
        results = (
            self.session.query(Event.event_type, func.count(Event.id).label("count"))
            .filter(Event.run_id == run_id)
            .group_by(Event.event_type)
            .all()
        )

        return {event_type: count for event_type, count in results}

    def count_errors(self, run_id: str) -> int:
        """
        Count error-severity events for a run.

        Args:
            run_id: Run ID to count errors for

        Returns:
            Number of error events
        """
        return (
            self.session.query(func.count(Event.id))
            .filter(Event.run_id == run_id, Event.severity == "error")
            .scalar()
            or 0
        )

    def get_latest_by_type(self, run_id: str, event_type: str) -> Event | None:
        """
        Get the latest event of a specific type for a run.

        Args:
            run_id: Run ID
            event_type: Event type to fetch

        Returns:
            Latest event or None
        """
        return (
            self.session.query(Event)
            .filter(Event.run_id == run_id, Event.event_type == event_type)
            .order_by(Event.timestamp.desc())
            .first()
        )

    def get_by_correlation(self, correlation_id: str, limit: int = 100) -> list[Event]:
        """
        Get all events with a specific correlation ID (for tracing).

        Args:
            correlation_id: Correlation ID to trace
            limit: Maximum number of events

        Returns:
            List of correlated events ordered by timestamp
        """
        return (
            self.session.query(Event)
            .filter(Event.correlation_id == correlation_id)
            .order_by(Event.timestamp.asc())
            .limit(limit)
            .all()
        )
