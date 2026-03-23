"""Step write repository."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
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
        step_type: str,
        status: str = "queued",
        attempt: int = 1,
    ) -> Step:
        """Append new step to run."""
        step = Step(
            id=str(uuid4()),
            run_id=run_id,
            number=number,
            name=name,
            step_type=step_type,
            status=status,
            attempt=attempt,
            retry_count=0,
        )
        return self.add(step)

    def mark_running(self, step_id: str) -> Step | None:
        """Mark step as running."""
        step = self.get(step_id)
        if step:
            step.status = "running"
            step.start_ts = datetime.now(UTC)
        return step

    def mark_completed(self, step_id: str) -> Step | None:
        """Mark step as completed."""
        step = self.get(step_id)
        if step:
            step.status = "completed"
            step.end_ts = datetime.now(UTC)
            if step.start_ts:
                step.duration_ms = int((step.end_ts - step.start_ts).total_seconds() * 1000)
        return step

    def mark_failed(self, step_id: str, error: dict) -> Step | None:
        """Mark step as failed with error."""
        step = self.get(step_id)
        if step:
            step.status = "failed"
            step.error = error
            step.end_ts = datetime.now(UTC)
            if step.start_ts:
                step.duration_ms = int((step.end_ts - step.start_ts).total_seconds() * 1000)
        return step

    def mark_suspended(self, step_id: str) -> Step | None:
        """Mark step as suspended."""
        step = self.get(step_id)
        if step:
            step.status = "suspended"
        return step

    def increment_retry(self, step_id: str) -> Step | None:
        """Increment retry count."""
        step = self.get(step_id)
        if step:
            step.retry_count += 1
        return step

    def get_last_for_run(self, run_id: str) -> Step | None:
        """Get last step for a run by number."""
        stmt = select(Step).where(Step.run_id == run_id).order_by(Step.number.desc()).limit(1)
        return self.session.scalar(stmt)

    def get_first_failed_for_run(self, run_id: str) -> Step | None:
        """Get first failed step for a run (latest attempt only).

        Uses a subquery to find the max attempt per step name, then filters
        to only failed steps from the latest attempt of each.
        """
        # Subquery: max attempt per (run_id, name)
        max_attempt_sq = (
            select(Step.name, func.max(Step.attempt).label("max_attempt"))
            .where(Step.run_id == run_id)
            .group_by(Step.name)
            .subquery()
        )

        stmt = (
            select(Step)
            .join(
                max_attempt_sq,
                (Step.name == max_attempt_sq.c.name)
                & (Step.attempt == max_attempt_sq.c.max_attempt),
            )
            .where(Step.run_id == run_id)
            .where(Step.status == "failed")
            .order_by(Step.number.asc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def get_by_name(self, run_id: str, step_name: str) -> Step | None:
        """Get step by run_id and step name (latest attempt)."""
        stmt = (
            select(Step)
            .where(Step.run_id == run_id)
            .where(Step.name == step_name)
            .order_by(Step.attempt.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def get_max_attempt(self, run_id: str, step_name: str) -> int:
        """Get the highest attempt number for a step name in a run. Returns 0 if none."""
        stmt = (
            select(func.max(Step.attempt))
            .where(Step.run_id == run_id)
            .where(Step.name == step_name)
        )
        result = self.session.scalar(stmt)
        return result or 0

    def get_latest_attempts_for_run(self, run_id: str) -> list[Step]:
        """Get the latest attempt of each step for a run.

        Returns one Step per step name — the one with the highest attempt number.
        Ordered by number ASC.
        """
        max_attempt_sq = (
            select(Step.name, func.max(Step.attempt).label("max_attempt"))
            .where(Step.run_id == run_id)
            .group_by(Step.name)
            .subquery()
        )

        stmt = (
            select(Step)
            .join(
                max_attempt_sq,
                (Step.name == max_attempt_sq.c.name)
                & (Step.attempt == max_attempt_sq.c.max_attempt),
            )
            .where(Step.run_id == run_id)
            .order_by(Step.number.asc())
        )
        return list(self.session.scalars(stmt).all())
