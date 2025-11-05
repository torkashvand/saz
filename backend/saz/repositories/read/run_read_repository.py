"""Run read repository for CQRS queries."""
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.orm import Session, joinedload

from saz.db.models import Run, Flow, Step, Artifact
from saz.repositories.read.dtos import RunListItemDTO, RunDetailDTO, StepSummaryDTO


class RunReadRepository:
    """Read repository for Run queries (CQRS)."""

    def __init__(self, session: Session):
        self.session = session

    def list(
        self,
        flow_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
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
                status=run.status,
                created_at=run.created_at,
                completed_at=run.completed_at,
                cost_cents=run.cost_cents
            )
            for run in runs
        ]

        return items, total

    def detail(self, run_id: str) -> Optional[RunDetailDTO]:
        """Get run detail with steps eagerly loaded."""
        stmt = (
            select(Run)
            .where(Run.id == run_id)
            .options(
                joinedload(Run.flow),
                joinedload(Run.steps),
                joinedload(Run.artifacts)
            )
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
                status=step.status,
                start_ts=step.start_ts,
                end_ts=step.end_ts,
                duration_ms=step.duration_ms,
                retry_count=step.retry_count,
                error=step.error
            )
            for step in sorted(run.steps, key=lambda s: s.number)
        ]

        return RunDetailDTO(
            id=run.id,
            flow_id=run.flow_id,
            flow_name=run.flow.name,
            status=run.status,
            payload=run.payload,
            error=run.error,
            cost_cents=run.cost_cents,
            created_at=run.created_at,
            completed_at=run.completed_at,
            steps=steps,
            artifact_count=len(run.artifacts)
        )