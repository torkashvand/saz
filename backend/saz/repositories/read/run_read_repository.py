"""Run read repository for CQRS queries."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from saz.db.models import Run
from saz.domain.literals import RunStatus, StepStatus
from saz.repositories.read.dtos import RunDetailDTO, RunListItemDTO, StepSummaryDTO


class RunReadRepository:
    """Read repository for Run queries (CQRS)."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, run_id: str) -> Run | None:
        """Get a run by ID."""
        stmt = select(Run).where(Run.id == run_id)
        return self.session.scalar(stmt)

    def list(
        self,
        flow_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RunListItemDTO], int]:
        """List runs with filters and pagination."""
        # Build query
        stmt = select(Run)

        if flow_id:
            stmt = stmt.where(Run.flow_id == flow_id)
        if status:
            stmt = stmt.where(Run.status == status)

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.session.scalar(count_stmt) or 0

        # Apply pagination and ordering
        stmt = stmt.order_by(Run.created_at.desc()).limit(limit).offset(offset)

        # Execute
        runs = self.session.scalars(stmt).all()

        # Map to DTOs
        items = [
            RunListItemDTO(
                id=run.id,
                flow_id=run.flow_id,
                status=RunStatus(run.status),
                created_at=run.created_at,
                completed_at=run.completed_at,
                cost_cents=run.cost_cents,
                error=run.error,
            )
            for run in runs
        ]

        return items, total

    def detail(self, run_id: str) -> RunDetailDTO | None:
        """Get run detail with steps eagerly loaded."""
        stmt = (
            select(Run)
            .where(Run.id == run_id)
            .options(joinedload(Run.flow), joinedload(Run.steps), joinedload(Run.artifacts))
        )

        run = self.session.scalar(stmt)
        if not run:
            return None

        # Map steps
        steps = [
            StepSummaryDTO(
                id=step.id,
                number=step.number,
                name=step.name,
                attempt=step.attempt,
                status=StepStatus(step.status),
                start_ts=step.start_ts,
                end_ts=step.end_ts,
                duration_ms=step.duration_ms,
                retry_count=step.retry_count,
                output=step.output,
                error=step.error,
                input=step.input,
                tokens=step.tokens,
                cost_usd=step.cost_usd,
                critique=step.critique,
                policy_flags=step.policy_flags,
                step_type=step.step_type,
            )
            for step in sorted(run.steps, key=lambda s: (s.number, s.attempt))
        ]

        return RunDetailDTO(
            id=run.id,
            flow_id=run.flow_id,
            flow_name=run.flow.name,
            status=RunStatus(run.status),
            payload=run.payload,
            error=run.error,
            cost_cents=run.cost_cents,
            created_at=run.created_at,
            completed_at=run.completed_at,
            steps=steps,
            artifact_count=len(run.artifacts),
        )
