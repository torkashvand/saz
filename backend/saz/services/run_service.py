"""Run service - business logic for run operations."""

from saz.db.unit_of_work import UnitOfWork
from saz.domain.literals import RunStatus
from saz.repositories.read.dtos import RunDetailDTO, RunListItemDTO


def resolve_suspended_step_on_approval(
    uow: UnitOfWork, step_id: str, run_error: dict | None, resume_data: dict
) -> None:
    """Resolve a suspended step when its run is approved/resumed.

    A pre-execution escalation suspended the step BEFORE its tool ran.
    Completing it would make the executor skip it forever — the approval
    payload would masquerade as tool output. Mark it failed with an
    ``escalation_approved`` marker instead: the executor re-runs failed
    steps as a new attempt and honors the recorded approval when the
    verifier escalates again.

    Every other suspension (human approval gates, webhook waits,
    post-execution escalation where the tool already ran) completes the
    step so execution advances past it — re-running those would double
    the side effect.
    """
    assert uow.steps is not None
    step_entity = uow.steps.get(step_id)
    if step_entity is None:
        return

    error = run_error or {}
    if error.get("type") == "EscalationRequired" and error.get("pre_execution"):
        step_entity.output = {**resume_data, "escalation_approved": True}
        uow.steps.mark_failed(
            step_id,
            {
                "message": "Pre-execution escalation approved; step will re-execute",
                "type": "EscalationApproved",
                "category": "escalation",
                "retryable": True,
            },
        )
    else:
        step_entity.output = resume_data
        uow.steps.mark_completed(step_id)


class RunService:
    """Service for run operations."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    def create(self, flow_id: str, payload: dict, created_by_user_id: str) -> str:
        """Create a new run."""
        assert self.uow.flows is not None
        assert self.uow.runs is not None
        # Verify flow exists
        flow = self.uow.flows.get(flow_id)
        if not flow:
            raise ValueError(f"Flow not found: {flow_id}")

        # Create run
        run = self.uow.runs.create(flow_id, payload, created_by_user_id=created_by_user_id)
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

        if run_detail.status != RunStatus.FAILED:
            raise ValueError(f"Can only retry failed runs, got: {run_detail.status}")

        # Find the first failing step (latest attempt)
        failing_step = self.uow.steps.get_first_failed_for_run(run_id)
        if not failing_step:
            raise ValueError("No failing step found")

        # Reset run to queued — same run, same id
        run = self.uow.runs.get(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")

        run.status = RunStatus.QUEUED
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

        # Get run detail (used to locate the suspended step).
        run_detail = self.uow.run_reads.detail(run_id)
        if not run_detail:
            raise ValueError(f"Run not found: {run_id}")

        # Atomically claim the suspended run BEFORE mutating any step state.
        # This closes the resume-vs-timeout race: if the SuspensionSweeper has
        # already failed the run, the guarded UPDATE matches zero rows and we
        # must not resurrect it. (Mirrors mark_failed_if_suspended on the
        # sweeper side.)
        if not self.uow.runs.mark_queued_if_suspended(run_id):
            current = self.uow.runs.get(run_id)
            status = current.status if current is not None else "missing"
            raise ValueError(f"Run {run_id} is not suspended (status: {status})")

        # Now that we own the transition, resolve the suspended step. Leaving
        # it suspended while requeuing the run causes the executor to either
        # re-enter the same gate or never advance it (only completed steps are
        # skipped on restart). When the caller does not provide explicit
        # resume_data, store a minimal "resumed" marker so the output is a dict.
        suspended_step = next((s for s in run_detail.steps if s.status == "suspended"), None)
        if suspended_step:
            resolve_suspended_step_on_approval(
                self.uow,
                suspended_step.id,
                run_detail.error,
                resume_data or {"resumed": True},
            )

        # Apply payload override now that the run is queued.
        if override_payload:
            run = self.uow.runs.get(run_id)
            if run:
                run.payload = {**run.payload, **override_payload}

        self.uow.commit()
