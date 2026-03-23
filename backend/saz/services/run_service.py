"""Run service - business logic for run operations."""

from saz.db.unit_of_work import UnitOfWork
from saz.repositories.read.dtos import RunDetailDTO, RunListItemDTO


class RunService:
    """Service for run operations."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    def create(self, flow_id: str, payload: dict) -> str:
        """Create a new run."""
        assert self.uow.flows is not None
        assert self.uow.runs is not None
        # Verify flow exists
        flow = self.uow.flows.get(flow_id)
        if not flow:
            raise ValueError(f"Flow not found: {flow_id}")

        # Create run
        run = self.uow.runs.create(flow_id, payload)
        self.uow.commit()

        return run.id

    def get(self, run_id: str) -> RunDetailDTO | None:
        """Get run detail."""
        assert self.uow.run_reads is not None
        return self.uow.run_reads.detail(run_id)

    def list(
        self,
        flow_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RunListItemDTO], int]:
        """List runs with filters."""
        assert self.uow.run_reads is not None
        return self.uow.run_reads.list(flow_id, status, limit, offset)

    def mark_running(self, run_id: str) -> None:
        """Mark run as running."""
        assert self.uow.runs is not None
        run = self.uow.runs.mark_running(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")
        self.uow.commit()

    def mark_completed(self, run_id: str) -> None:
        """Mark run as completed."""
        assert self.uow.runs is not None
        run = self.uow.runs.mark_completed(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")
        self.uow.commit()

    def mark_failed(self, run_id: str, error: dict) -> None:
        """Mark run as failed."""
        assert self.uow.runs is not None
        run = self.uow.runs.mark_failed(run_id, error)
        if not run:
            raise ValueError(f"Run not found: {run_id}")
        self.uow.commit()

    def mark_suspended(self, run_id: str, reason: str) -> None:
        """Mark run as suspended."""
        assert self.uow.runs is not None
        run = self.uow.runs.mark_suspended(run_id, {"reason": reason})
        if not run:
            raise ValueError(f"Run not found: {run_id}")
        self.uow.commit()

    def retry(self, run_id: str) -> None:
        """Retry a failed run from the point of failure (same-run semantics).

        The same run is reused. Historical failed/completed step attempts are
        preserved. The run is reset to 'queued' so the scheduler can pick it
        up again. The executor will restore context from the latest completed
        attempts and skip them, then re-execute from the failing step onward.
        """
        assert self.uow.runs is not None
        assert self.uow.steps is not None
        assert self.uow.run_reads is not None

        run_detail = self.uow.run_reads.detail(run_id)
        if not run_detail:
            raise ValueError(f"Run not found: {run_id}")

        if run_detail.status not in ("failed", "error"):
            raise ValueError(f"Can only retry failed runs, got: {run_detail.status}")

        # Find the first failing step (latest attempt)
        failing_step = self.uow.steps.get_first_failed_for_run(run_id)
        if not failing_step:
            raise ValueError("No failing step found")

        # Reset run to queued — same run, same id
        run = self.uow.runs.get(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")

        run.status = "queued"
        run.error = None
        run.completed_at = None

        self.uow.commit()

    def resume_run(
        self,
        run_id: str,
        resume_data: dict | None = None,
        override_payload: dict | None = None,
    ) -> None:
        """
        Resume a suspended run.

        Args:
            run_id: Run identifier
            resume_data: Data from approval/callback (stored in suspended step's output)
            override_payload: Optional payload overrides for resumption

        Raises:
            ValueError: If run not found or not suspended
        """
        assert self.uow.runs is not None
        assert self.uow.steps is not None
        assert self.uow.run_reads is not None

        # Get run detail
        run_detail = self.uow.run_reads.detail(run_id)
        if not run_detail:
            raise ValueError(f"Run not found: {run_id}")

        if run_detail.status != "suspended":
            raise ValueError(f"Run {run_id} is not suspended (status: {run_detail.status})")

        # Find the suspended step
        suspended_step = None
        for step in run_detail.steps:
            if step.status == "suspended":
                suspended_step = step
                break

        # Store resume data in the suspended step's output
        if suspended_step and resume_data:
            step_entity = self.uow.steps.get(suspended_step.id)
            if step_entity:
                step_entity.output = resume_data
                # Mark step as completed
                self.uow.steps.mark_completed(suspended_step.id)

        # Update run payload if override provided and mark as queued
        run = self.uow.runs.get(run_id)
        if run:
            if override_payload:
                # Create new dict to trigger SQLAlchemy update detection
                updated_payload = {**run.payload, **override_payload}
                run.payload = updated_payload

            run.status = "queued"
            run.error = None  # Clear suspension error

        self.uow.commit()
