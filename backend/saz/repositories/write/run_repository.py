"""Run write repository."""
from datetime import datetime, UTC
from typing import Optional
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
            created_at=datetime.now(UTC)
        )
        return self.add(run)

    def mark_running(self, run_id: str) -> Optional[Run]:
        """Mark run as running."""
        run = self.get(run_id)
        if run:
            run.status = "running"
        return run

    def mark_completed(self, run_id: str) -> Optional[Run]:
        """Mark run as completed."""
        run = self.get(run_id)
        if run:
            run.status = "completed"
            run.completed_at = datetime.now(UTC)
        return run

    def mark_failed(self, run_id: str, error: dict) -> Optional[Run]:
        """Mark run as failed with error."""
        run = self.get(run_id)
        if run:
            run.status = "failed"
            run.error = error
            run.completed_at = datetime.now(UTC)
        return run

    def mark_suspended(self, run_id: str, error: Optional[dict] = None) -> Optional[Run]:
        """Mark run as suspended."""
        run = self.get(run_id)
        if run:
            run.status = "suspended"
            if error:
                run.error = error
        return run

    def update_cost(self, run_id: str, cost_cents: int) -> Optional[Run]:
        """Update run cost."""
        run = self.get(run_id)
        if run:
            run.cost_cents = cost_cents
        return run

    def add_cost(self, run_id: str, additional_cents: int) -> Optional[Run]:
        """Add to run cost."""
        run = self.get(run_id)
        if run:
            run.cost_cents += additional_cents
        return run