"""Run scheduler using ThreadPoolExecutor for in-process execution."""

import asyncio
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from saz.db.unit_of_work import UnitOfWork

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class RunScheduler:
    """Singleton scheduler for executing runs in background threads."""

    _instance: Optional["RunScheduler"] = None
    _lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "RunScheduler":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, database_url: str, max_workers: int | None = None):
        # Only initialize once
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        self.database_url = database_url
        self.max_workers = max_workers or int(os.environ.get("EXECUTOR_MAX_WORKERS", "4"))
        self.executor = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="run-worker"
        )
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self._running_runs: set[str] = set()
        self._running_lock = threading.Lock()

        logger.info(f"RunScheduler initialized with {self.max_workers} workers")

    def schedule(self, run_id: str) -> bool:
        """Schedule a run for execution. Returns True if scheduled, False if already running."""
        with self._running_lock:
            if run_id in self._running_runs:
                logger.warning(f"Run {run_id} is already scheduled/running")
                return False
            self._running_runs.add(run_id)

        logger.info(f"Scheduling run {run_id} for execution")
        self.executor.submit(self._execute_run_sync, run_id)
        return True

    def _execute_run_sync(self, run_id: str) -> None:
        """Execute a run synchronously in a thread."""
        # Lazy import to avoid circular dependency
        from saz.engine.executor import WorkflowExecutor
        from saz.globals import (
            create_critic_agent,
            create_executor_agent,
            create_planner,
            create_policy_engine,
            get_tool_registry,
        )

        fatal = False
        try:
            logger.info(f"Thread started for run {run_id}")
            session = self.SessionLocal()
            try:
                # Create event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                with UnitOfWork(session) as uow:
                    # Get flow to determine planner_mode
                    assert uow.run_reads is not None
                    run = uow.run_reads.detail(run_id)
                    planner_mode = "deterministic"  # Default fallback
                    if run:
                        assert uow.flows is not None
                        flow = uow.flows.get(run.flow_id)
                        if flow:
                            planner_mode = flow.definition.get("workflow", {}).get(
                                "planner_mode", "deterministic"
                            )

                    # Build fresh, run-isolated agents. Only the tool registry
                    # is shared (immutable tool specs); the policy engine,
                    # executor agent, critic, and planner each hold per-run
                    # mutable state and must not be shared across concurrent runs.
                    executor = WorkflowExecutor(
                        uow=uow,
                        tool_registry=get_tool_registry(),
                        planner=create_planner(planner_mode),
                        executor_agent=create_executor_agent(),
                        critic=create_critic_agent(),
                        policy_engine=create_policy_engine(),
                    )
                    loop.run_until_complete(executor.execute_run(run_id))

                loop.close()
                logger.info(f"Thread completed for run {run_id}")
            finally:
                session.close()
        except Exception as e:
            fatal = True
            logger.exception(f"Fatal error in thread for run {run_id}: {e}")
        finally:
            with self._running_lock:
                self._running_runs.discard(run_id)
            # Not after a fatal error: a run whose thread keeps crashing
            # before it can leave "queued" must not requeue-loop forever.
            if not fatal:
                self._reschedule_if_requeued(run_id)

    def _reschedule_if_requeued(self, run_id: str) -> None:
        """Resubmit a run that was re-queued during this thread's teardown.

        A resume/callback landing between the suspension commit and the
        ``_running_runs`` discard flips the run to ``queued``, but its
        ``schedule()`` call was refused because this thread still held the
        id. Nothing rescans queued runs, so without this re-check the run is
        stranded in ``queued`` forever.
        """
        try:
            session = self.SessionLocal()
            try:
                with UnitOfWork(session) as uow:
                    assert uow.runs is not None
                    run = uow.runs.get(run_id)
                    status = run.status if run else None
            finally:
                session.close()
        except Exception as e:
            logger.exception(f"Post-run status re-check failed for run {run_id}: {e}")
            return
        if status == "queued":
            logger.info(f"Run {run_id} was re-queued during teardown; rescheduling")
            self.schedule(run_id)

    def shutdown(self, wait: bool = False) -> None:
        """Shutdown the executor."""
        logger.info(f"Shutting down RunScheduler (wait={wait})")
        self.executor.shutdown(wait=wait)

        # Mark all running runs as failed
        if not wait and self._running_runs:
            session = self.SessionLocal()
            try:
                with UnitOfWork(session) as uow:
                    assert uow.runs is not None
                    for run_id in list(self._running_runs):
                        try:
                            uow.runs.mark_failed(
                                run_id, {"message": "Server shutdown", "type": "ShutdownError"}
                            )
                            uow.commit()
                            logger.info(f"Marked run {run_id} as failed due to shutdown")
                        except Exception as e:
                            logger.error(f"Failed to mark run {run_id} as failed: {e}")
            finally:
                session.close()


# Global scheduler instance
_scheduler: RunScheduler | None = None
_scheduler_lock = threading.Lock()


def get_scheduler(database_url: str | None = None) -> RunScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        with _scheduler_lock:
            if _scheduler is None:
                if database_url is None:
                    database_url = os.environ.get("DATABASE_URL")
                    if not database_url:
                        raise ValueError("DATABASE_URL not configured")
                _scheduler = RunScheduler(database_url)
    return _scheduler
