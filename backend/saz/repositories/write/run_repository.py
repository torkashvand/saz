"""Run write repository."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from saz.db.models import Run
from saz.domain.literals import RunStatus
from saz.repositories.base import BaseRepository


class RunRepository(BaseRepository[Run]):
    """Write repository for Run aggregate."""

    def __init__(self, session: Session):
        super().__init__(session, Run)

    def create(self, flow_id: str, payload: dict, created_by_user_id: str) -> Run:
        """Create new run.

        Copies the parent Flow's planner_mode onto the Run row so the API
        response and audit events reflect what the flow actually executes
        as (not just the model column default).
        """
        from saz.db.models import Flow

        flow = self.session.get(Flow, flow_id)
        planner_mode = "deterministic"
        if flow and isinstance(flow.definition, dict):
            workflow_def = flow.definition.get("workflow", {})
            planner_mode = workflow_def.get("planner_mode", "deterministic")

        run = Run(
            id=str(uuid4()),
            flow_id=flow_id,
            status=RunStatus.QUEUED,
            planner_mode=planner_mode,
            payload=payload,
            cost_cents=0,
            created_at=datetime.now(UTC),
            created_by_user_id=created_by_user_id,
        )
        return self.add(run)

    def mark_running(self, run_id: str) -> Run | None:
        """Mark run as running, recording started_at so duration_ms reflects
        actual execution time rather than queue + suspension wait."""
        run = self.get(run_id)
        if run:
            run.status = RunStatus.RUNNING
            if run.started_at is None:
                run.started_at = datetime.now(UTC)
        return run

    def _set_duration_ms(self, run: Run) -> None:
        """Populate run.duration_ms from started_at → completed_at.

        SQLite strips tzinfo on round-trip even though the column is declared
        DateTime(timezone=True); PostgreSQL preserves it. Normalize both
        sides to UTC-aware before subtracting so the call works on either
        backend.
        """
        if run.started_at is None or run.completed_at is None:
            return
        started = run.started_at
        completed = run.completed_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=UTC)
        run.duration_ms = int((completed - started).total_seconds() * 1000)

    def mark_completed(self, run_id: str) -> Run | None:
        """Mark run as completed.

        Persists duration_ms (started_at → completed_at) so the column is
        not left NULL and consumers don't need to recompute it from
        created_at, which would include queue + suspension time.
        """
        run = self.get(run_id)
        if run:
            run.status = RunStatus.COMPLETED
            run.completed_at = datetime.now(UTC)
            self._set_duration_ms(run)
        return run

    def mark_failed(self, run_id: str, error: dict) -> Run | None:
        """Mark run as failed with error."""
        run = self.get(run_id)
        if run:
            run.status = RunStatus.FAILED
            run.error = error
            run.completed_at = datetime.now(UTC)
            self._set_duration_ms(run)
        return run

    def mark_suspended(self, run_id: str, error: dict | None = None) -> Run | None:
        """Mark run as suspended."""
        run = self.get(run_id)
        if run:
            run.status = RunStatus.SUSPENDED
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

    def find_expired_suspensions(self, now: datetime, limit: int = 100) -> list[Run]:
        """Return suspended runs whose timeout_at deadline has passed.

        The executor writes ``error.timeout_at`` (ISO timestamp) when it
        suspends on ``human.approval`` or ``webhook.wait``. The
        SuspensionSweeper uses this to fail runs whose external callback
        never arrived, so stuck runs do not accumulate.

        SQLite's JSON_EXTRACT returns the raw stored text, which for our
        ISO-8601 timestamps sorts lexicographically the same as
        chronologically (both are zero-padded). Comparing strings keeps
        this query portable across SQLite and PostgreSQL without any
        per-dialect casting.

        Args:
            now: Current UTC time. Runs with timeout_at <= now are returned.
            limit: Cap to avoid pulling thousands of runs in a single sweep.

        Returns:
            List of Run rows that have expired and are still suspended.
        """
        # Compare ISO timestamp strings directly. Both sides are
        # zero-padded UTC ISO-8601 strings so string ordering matches
        # chronological ordering.
        now_iso = now.astimezone(UTC).isoformat()
        stmt = (
            select(Run)
            .where(Run.status == RunStatus.SUSPENDED)
            .where(Run.error.isnot(None))
            .where(Run.error["timeout_at"].as_string().isnot(None))
            .where(Run.error["timeout_at"].as_string() <= now_iso)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())
