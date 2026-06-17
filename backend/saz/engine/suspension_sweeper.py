"""Periodic sweeper that fails suspended runs whose deadline has passed.

When the executor suspends a run on a ``human.approval`` or ``webhook.wait``
step it records ``error.timeout_at`` (ISO-8601 UTC). The SuspensionSweeper
runs on an APScheduler interval, finds suspensions whose deadline has
elapsed, transitions them to ``failed`` with type ``SuspensionTimeout``,
and emits the corresponding audit events.

This keeps the suspended-runs set bounded: external systems may forget to
callback, operators may miss approval windows, and the demos use shorter
windows that should always close.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from saz.audit.event_emitter import EventEmitter
from saz.db.unit_of_work import UnitOfWork
from saz.domain.literals import SuspensionErrorType

logger = logging.getLogger(__name__)


# Job id is fixed so replace_existing=True can deduplicate registrations
# across hot reloads / test fixtures.
_SWEEP_JOB_ID = "saz_suspension_sweep"

# Conservative defaults — tuned so demos complete in seconds while not
# hammering the DB in production. Overridable via env in SuspensionSweeper.
_DEFAULT_INTERVAL_SECONDS = 60.0
_DEFAULT_BATCH_LIMIT = 100


class SuspensionSweeper:
    """Background job that times out stale ``suspended`` runs.

    Lifecycle:

      sweeper = SuspensionSweeper(database_url=...)
      sweeper.start()    # called from FastAPI lifespan startup
      ...
      sweeper.stop()     # called from FastAPI lifespan shutdown

    Designed to be safe to start exactly once per process. ``start()``
    is idempotent; ``stop()`` is idempotent.
    """

    def __init__(
        self,
        database_url: str,
        *,
        interval_seconds: float = _DEFAULT_INTERVAL_SECONDS,
        batch_limit: int = _DEFAULT_BATCH_LIMIT,
        engine: Engine | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")
        if batch_limit <= 0:
            raise ValueError("batch_limit must be > 0")

        self._database_url = database_url
        self._interval_seconds = interval_seconds
        self._batch_limit = batch_limit
        # Caller may pass a shared engine (used by tests). Otherwise we
        # build our own — the sweeper holds a single small connection
        # pool that runs in a background daemon thread.
        self._engine: Engine = engine or create_engine(database_url, pool_pre_ping=True)
        self._SessionLocal = sessionmaker(bind=self._engine)
        self._scheduler: BackgroundScheduler | None = None
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Start the background sweeper. Idempotent."""
        with self._lock:
            if self._scheduler is not None and self._scheduler.running:
                return
            scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
            scheduler.add_job(
                self.sweep_once,
                trigger="interval",
                seconds=self._interval_seconds,
                id=_SWEEP_JOB_ID,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                next_run_time=datetime.now(UTC),
            )
            scheduler.start()
            self._scheduler = scheduler
            logger.info(
                "suspension_sweeper_started interval=%ss batch_limit=%d",
                self._interval_seconds,
                self._batch_limit,
            )

    def stop(self) -> None:
        """Stop the sweeper. Idempotent."""
        with self._lock:
            scheduler = self._scheduler
            self._scheduler = None
        if scheduler is None:
            return
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            # APScheduler raises if the scheduler is not running. Stop is
            # idempotent — swallow.
            logger.debug("suspension_sweeper_shutdown_already_stopped", exc_info=True)
        logger.info("suspension_sweeper_stopped")

    # ----------------------------------------------------------------- sweep

    def sweep_once(self) -> int:
        """Run a single sweep pass.

        Returns the number of runs that were timed out. Exposed publicly
        so tests can drive the sweeper deterministically without waiting
        for the interval timer to fire.
        """
        now = datetime.now(UTC)
        session: Session = self._SessionLocal()
        timed_out = 0
        try:
            with UnitOfWork(session) as uow:
                assert uow.runs is not None
                expired = uow.runs.find_expired_suspensions(now, limit=self._batch_limit)
                if not expired:
                    uow.commit()
                    return 0

                for run in expired:
                    try:
                        self._fail_one(uow, run, now)
                        timed_out += 1
                    except Exception:
                        # One run misbehaving must not block the sweep.
                        logger.exception("suspension_sweeper_fail_one_failed run_id=%s", run.id)
                uow.commit()
        finally:
            session.close()

        if timed_out:
            logger.info("suspension_sweeper_timed_out count=%d", timed_out)
        return timed_out

    # ----------------------------------------------------------------- internals

    def _fail_one(self, uow: UnitOfWork, run: Any, now: datetime) -> None:
        """Mark a single suspended run as failed with SuspensionTimeout."""
        prior_error: dict[str, Any] = dict(run.error or {})
        step_id = prior_error.get("step_id", "")
        suspension_type = prior_error.get("type", "Suspension")
        timeout_at = prior_error.get("timeout_at")
        callback_id = prior_error.get("callback_id")

        # Build a fresh error that explains what happened, while preserving
        # the original suspension context for auditability.
        error: dict[str, Any] = {
            "message": (
                f"Suspension timed out for step {step_id}. "
                f"No callback or resume received before {timeout_at}."
            ),
            "type": "SuspensionTimeout",
            "step_id": step_id,
            "original_type": suspension_type,
            "timed_out_at": now.isoformat(),
        }
        if timeout_at is not None:
            error["timeout_at"] = timeout_at
        if callback_id is not None:
            # Preserve callback_id so a late callback can find the run and
            # respond with already_processed instead of 404.
            error["callback_id"] = callback_id

        assert uow.runs is not None
        # Atomic guard: only fail if STILL suspended. A concurrent resume that
        # committed after this run was discovered will have moved it to queued;
        # in that case rowcount is 0 and we must not touch it or emit events.
        if not uow.runs.mark_failed_if_suspended(run.id, error):
            logger.info("suspension_sweeper_skip_not_suspended run_id=%s", run.id)
            return

        # Fail any step that was sitting on the suspension so the UI does
        # not show a "suspended" step under a "failed" run. Step.error must
        # be a dict — error_categorization.categorize_error and the rest of
        # the audit pipeline call ``.get("type")`` on it, and a bare string
        # would AttributeError out of the run-detail API.
        assert uow.steps is not None
        suspended_step = uow.steps.get_first_suspended_for_run(run.id)
        # events.step_id is an FK to steps.id; use the real row id (or None),
        # never the YAML step name from the suspension payload.
        suspended_step_db_id = suspended_step.id if suspended_step is not None else None
        if suspended_step is not None:
            suspended_step.status = "failed"
            suspended_step.error = {
                "message": error["message"],
                "type": "SuspensionTimeout",
            }

        # Emit audit events so the timeline shows what happened. The
        # emitter writes through to ``uow.emit_event`` which buffers
        # records; the outer ``uow.commit()`` in :meth:`sweep_once`
        # persists them. WebSocket broadcast is intentionally skipped
        # here because the sweeper is a sync background job — clients
        # pick up the SuspensionTimeout on their next run-detail refetch.
        emitter = EventEmitter(
            uow=uow,
            run_id=run.id,
            planner_mode=run.planner_mode or "deterministic",
            pii_policy="redact",
        )
        if suspension_type == SuspensionErrorType.HUMAN_APPROVAL_REQUIRED:
            emitter.approval_denied(
                step_id=suspended_step_db_id,
                step_name=step_id,
                reason="Suspension timed out before approval",
            )
        emitter.run_failed(
            error=error["message"],
            error_type="SuspensionTimeout",
        )


# ---------------------------------------------------------------------------
# Module-level singleton — mirrors RunScheduler's pattern.
# ---------------------------------------------------------------------------

_sweeper: SuspensionSweeper | None = None
_sweeper_lock = threading.Lock()


def get_suspension_sweeper(
    database_url: str | None = None,
    *,
    interval_seconds: float | None = None,
    batch_limit: int | None = None,
) -> SuspensionSweeper:
    """Return the process-wide SuspensionSweeper, building it on first call."""
    global _sweeper
    with _sweeper_lock:
        if _sweeper is None:
            if database_url is None:
                import os

                database_url = os.environ.get("DATABASE_URL")
                if not database_url:
                    raise ValueError("DATABASE_URL not configured for SuspensionSweeper")
            kwargs: dict[str, Any] = {}
            if interval_seconds is not None:
                kwargs["interval_seconds"] = interval_seconds
            if batch_limit is not None:
                kwargs["batch_limit"] = batch_limit
            _sweeper = SuspensionSweeper(database_url, **kwargs)
        return _sweeper


def reset_suspension_sweeper_for_tests() -> None:
    """Tear down the singleton — used by test fixtures to keep test
    isolation between processes that share the module state."""
    global _sweeper
    with _sweeper_lock:
        if _sweeper is not None:
            try:
                _sweeper.stop()
            except Exception:
                pass
            _sweeper = None
