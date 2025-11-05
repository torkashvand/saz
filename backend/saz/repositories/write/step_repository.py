"""Step write repository."""
from datetime import datetime, UTC
from typing import Optional
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session

from saz.db.models import Step
from saz.repositories.base import BaseRepository


class StepRepository(BaseRepository[Step]):
    """Write repository for Step entity."""

    def __init__(self, session: Session):
        super().__init__(session, Step)

    def append(
        self,
        run_id: str,
        number: int,
        name: str,
        status: str = "queued"
    ) -> Step:
        """Append new step to run."""
        step = Step(
            id=str(uuid4()),
            run_id=run_id,
            number=number,
            name=name,
            status=status,
            retry_count=0
        )
        return self.add(step)

    def mark_running(self, step_id: str) -> Optional[Step]:
        """Mark step as running."""
        step = self.get(step_id)
        if step:
            step.status = "running"
            step.start_ts = datetime.now(UTC)
        return step

    def mark_completed(self, step_id: str) -> Optional[Step]:
        """Mark step as completed."""
        step = self.get(step_id)
        if step:
            step.status = "completed"
            step.end_ts = datetime.now(UTC)
            if step.start_ts:
                step.duration_ms = int((step.end_ts - step.start_ts).total_seconds() * 1000)
        return step

    def mark_failed(self, step_id: str, error: dict) -> Optional[Step]:
        """Mark step as failed with error."""
        step = self.get(step_id)
        if step:
            step.status = "failed"
            step.error = error
            step.end_ts = datetime.now(UTC)
            if step.start_ts:
                step.duration_ms = int((step.end_ts - step.start_ts).total_seconds() * 1000)
        return step

    def mark_suspended(self, step_id: str) -> Optional[Step]:
        """Mark step as suspended."""
        step = self.get(step_id)
        if step:
            step.status = "suspended"
        return step

    def increment_retry(self, step_id: str) -> Optional[Step]:
        """Increment retry count."""
        step = self.get(step_id)
        if step:
            step.retry_count += 1
        return step

    def get_last_for_run(self, run_id: str) -> Optional[Step]:
        """Get last step for a run by number."""
        stmt = (
            select(Step)
            .where(Step.run_id == run_id)
            .order_by(Step.number.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def get_first_failed_for_run(self, run_id: str) -> Optional[Step]:
        """Get first failed step for a run."""
        stmt = (
            select(Step)
            .where(Step.run_id == run_id)
            .where(Step.status == "failed")
            .order_by(Step.number.asc())
            .limit(1)
        )
        return self.session.scalar(stmt)