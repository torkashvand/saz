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

        try:
            logger.info(f"Thread started for run {run_id}")
            session = self.SessionLocal()
            try:
                # Create event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                with UnitOfWork(session) as uow:
                    executor = WorkflowExecutor(uow)
                    loop.run_until_complete(executor.execute_run(run_id))

                loop.close()
                logger.info(f"Thread completed for run {run_id}")
            finally:
                session.close()
        except Exception as e:
            logger.exception(f"Fatal error in thread for run {run_id}: {e}")
        finally:
            with self._running_lock:
                self._running_runs.discard(run_id)

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
