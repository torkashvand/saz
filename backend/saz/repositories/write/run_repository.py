"""Run write repository."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from saz.db.models import Run
from saz.repositories.base import BaseRepository


class RunRepository(BaseRepository[Run]):
    """Write repository for Run aggregate."""

    def __init__(self, session: Session):
        super().__init__(session, Run)

    def create(self, flow_id: str, payload: dict) -> Run:
        """Create new run."""
        run = Run(
            id=str(uuid4()),
            flow_id=flow_id,
            status="queued",
            payload=payload,
            cost_cents=0,
            created_at=datetime.now(UTC),
        )
        return self.add(run)

    def mark_running(self, run_id: str) -> Run | None:
        """Mark run as running."""
        run = self.get(run_id)
        if run:
            run.status = "running"
        return run

    def mark_completed(self, run_id: str) -> Run | None:
        """Mark run as completed."""
        run = self.get(run_id)
        if run:
            run.status = "completed"
            run.completed_at = datetime.now(UTC)
        return run

    def mark_failed(self, run_id: str, error: dict) -> Run | None:
        """Mark run as failed with error."""
        run = self.get(run_id)
        if run:
            run.status = "failed"
            run.error = error
            run.completed_at = datetime.now(UTC)
        return run

    def mark_suspended(self, run_id: str, error: dict | None = None) -> Run | None:
        """Mark run as suspended."""
        run = self.get(run_id)
        if run:
            run.status = "suspended"
            if error:
                run.error = error
        return run

    def update_cost(self, run_id: str, cost_cents: int) -> Run | None:
        """Update run cost."""
        run = self.get(run_id)
        if run:
            run.cost_cents = cost_cents
        return run

    def add_cost(self, run_id: str, additional_cents: int) -> Run | None:
        """Add to run cost."""
        run = self.get(run_id)
        if run:
            run.cost_cents += additional_cents
        return run

    def find_by_callback_id(self, callback_id: str) -> Run | None:
        """Find a run by its callback_id (stored in the error JSON).

        Searches all runs with an error dict containing the callback_id,
        not just suspended ones, so callers can detect already-processed
        callbacks and handle them idempotently.

        Uses a SQL-level JSON extraction so only the matching row is loaded,
        not every run with a non-null error dict.
        """
        # Use JSON path extraction at the SQL level so only the matching row
        # is loaded. .as_string() extracts the JSON value as a plain string
        # (avoids the extra quoting that cast(... String) produces in SQLite).
        stmt = (
            select(Run)
            .where(Run.error.isnot(None))
            .where(Run.error["callback_id"].as_string() == callback_id)
            .limit(1)
        )
        return self.session.scalar(stmt)
