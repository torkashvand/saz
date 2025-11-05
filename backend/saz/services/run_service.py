"""Run service - business logic for run operations."""
from typing import Optional
from saz.db.unit_of_work import UnitOfWork
from saz.repositories.read.dtos import RunListItemDTO, RunDetailDTO
from saz.domain.events import RunStarted, RunCompleted, RunFailed, RunSuspended


class RunService:
    """Service for run operations."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    def create(self, flow_id: str, payload: dict) -> str:
        """Create a new run."""
        # Verify flow exists
        flow = self.uow.flows.get(flow_id)
        if not flow:
            raise ValueError(f"Flow not found: {flow_id}")

        # Create run
        run = self.uow.runs.create(flow_id, payload)
        self.uow.commit()

        # Emit event
        self.uow.add_event(RunStarted(run.id, flow_id))

        return run.id

    def get(self, run_id: str) -> Optional[RunDetailDTO]:
        """Get run detail."""
        return self.uow.run_reads.detail(run_id)

    def list(
        self,
        flow_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> tuple[list[RunListItemDTO], int]:
        """List runs with filters."""
        return self.uow.run_reads.list(flow_id, status, limit, offset)

    def mark_running(self, run_id: str) -> None:
        """Mark run as running."""
        run = self.uow.runs.mark_running(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")
        self.uow.commit()

    def mark_completed(self, run_id: str) -> None:
        """Mark run as completed."""
        run = self.uow.runs.mark_completed(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")
        self.uow.commit()
        self.uow.add_event(RunCompleted(run_id))

    def mark_failed(self, run_id: str, error: dict) -> None:
        """Mark run as failed."""
        run = self.uow.runs.mark_failed(run_id, error)
        if not run:
            raise ValueError(f"Run not found: {run_id}")
        self.uow.commit()
        self.uow.add_event(RunFailed(run_id, error))

    def mark_suspended(self, run_id: str, reason: str) -> None:
        """Mark run as suspended."""
        run = self.uow.runs.mark_suspended(run_id, {"reason": reason})
        if not run:
            raise ValueError(f"Run not found: {run_id}")
        self.uow.commit()
        self.uow.add_event(RunSuspended(run_id, reason))

    def retry(self, run_id: str) -> str:
        """Retry a failed run by finding failing step and creating new run."""
        # Get original run
        run_detail = self.uow.run_reads.detail(run_id)
        if not run_detail:
            raise ValueError(f"Run not found: {run_id}")

        if run_detail.status != "failed":
            raise ValueError(f"Can only retry failed runs, got: {run_detail.status}")

        # Find first failing step
        failing_step = self.uow.steps.get_first_failed_for_run(run_id)
        if not failing_step:
            raise ValueError("No failing step found")

        # Reconstruct payload from original run
        # In a real system, you'd reconstruct state up to the failing step
        new_payload = run_detail.payload.copy()
        new_payload["_retry_from_run"] = run_id
        new_payload["_retry_from_step"] = failing_step.number

        # Create new run
        new_run_id = self.create(run_detail.flow_id, new_payload)

        return new_run_id

    def replay(self, run_id: str, from_step: int) -> str:
        """Replay a run from a specific step."""
        # Get original run
        run_detail = self.uow.run_reads.detail(run_id)
        if not run_detail:
            raise ValueError(f"Run not found: {run_id}")

        if from_step < 0 or from_step >= len(run_detail.steps):
            raise ValueError(f"Invalid step number: {from_step}")

        # Reconstruct payload
        new_payload = run_detail.payload.copy()
        new_payload["_replay_from_run"] = run_id
        new_payload["_replay_from_step"] = from_step

        # Create new run
        new_run_id = self.create(run_detail.flow_id, new_payload)

        return new_run_id
