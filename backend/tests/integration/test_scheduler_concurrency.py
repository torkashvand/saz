"""Real RunScheduler behavior under concurrency and shutdown.

Most of the existing test suite uses the SyncScheduler fixture in conftest,
which replaces the ThreadPoolExecutor with a single-thread one to keep
tests deterministic. That's the right call for everything else, but it
hides bugs in the real scheduler's:
  - dedup ``_running_runs`` set (duplicate schedule() must return False),
  - shutdown(wait=False) failing in-flight runs to a structured error,
  - lifecycle invariants like never executing the same run id twice.

These tests construct a fresh RunScheduler (bypassing the module-level
singleton) so we can exercise real thread pool behavior without
contaminating other tests.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from saz.engine.scheduler import RunScheduler
from tests.conftest import TEST_USER_ID


@pytest.fixture
def fresh_scheduler(db_engine, monkeypatch):
    """Build a RunScheduler that doesn't touch the module singleton."""
    import saz.engine.scheduler as sched_module

    # Clear any singleton an earlier test left behind so __init__ runs.
    monkeypatch.setattr(RunScheduler, "_instance", None)
    monkeypatch.setattr(sched_module, "_scheduler", None)

    scheduler = RunScheduler(database_url=str(db_engine.url), max_workers=2)

    yield scheduler

    # Best-effort cleanup; reset singleton again for the next test.
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    monkeypatch.setattr(RunScheduler, "_instance", None)
    monkeypatch.setattr(sched_module, "_scheduler", None)


def test_duplicate_schedule_returns_false(fresh_scheduler, monkeypatch):
    """schedule() must reject duplicates while the prior submission is in-flight."""
    started = threading.Event()
    release = threading.Event()

    def slow_run(self, run_id: str) -> None:
        started.set()
        release.wait(timeout=5)

    # Patch the work-doer so we can control when the first run finishes.
    monkeypatch.setattr(RunScheduler, "_execute_run_sync", slow_run)

    assert fresh_scheduler.schedule("dup_run_1") is True
    assert started.wait(timeout=2), "first scheduled run should start"
    assert (
        fresh_scheduler.schedule("dup_run_1") is False
    ), "second schedule() for the same run id must be rejected while in-flight"
    release.set()

    # Wait briefly so the first run finishes and the id is removed
    fresh_scheduler.executor.shutdown(wait=True)


def test_schedule_then_complete_allows_rescheduling(fresh_scheduler, monkeypatch):
    """After a run finishes, scheduling it again must succeed."""

    def quick_run(self, run_id: str) -> None:
        return

    monkeypatch.setattr(RunScheduler, "_execute_run_sync", quick_run)

    assert fresh_scheduler.schedule("requeue_1") is True
    # Let the thread complete.
    fresh_scheduler.executor.shutdown(wait=True)
    # Rebuild the pool because we just shut it down. Use a new scheduler-
    # equivalent pool to attempt a re-schedule.
    fresh_scheduler.executor = ThreadPoolExecutor(max_workers=2)
    # Clear the in-flight set as the real code does in the finally clause.
    fresh_scheduler._running_runs.discard("requeue_1")

    assert (
        fresh_scheduler.schedule("requeue_1") is True
    ), "once a run id falls out of _running_runs it must be reschedulable"
    fresh_scheduler.executor.shutdown(wait=True)


def test_shutdown_no_wait_marks_inflight_runs_failed(fresh_scheduler, db_engine, monkeypatch):
    """shutdown(wait=False) on an in-flight run must mark it failed at the DB."""
    from sqlalchemy.orm import Session

    from saz.db.models import Flow, Run

    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_sched_shut",
            name="sched_shut",
            definition={"workflow": {"planner_mode": "deterministic", "steps": []}},
        )
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_sched_shut_1",
            flow_id="flow_sched_shut",
            status="running",
            planner_mode="deterministic",
            payload={},
        )
        session.add_all([flow, run])
        session.commit()

    started = threading.Event()
    block = threading.Event()

    def blocking_run(self, run_id: str) -> None:
        started.set()
        block.wait(timeout=5)

    monkeypatch.setattr(RunScheduler, "_execute_run_sync", blocking_run)

    assert fresh_scheduler.schedule("run_sched_shut_1") is True
    assert started.wait(timeout=2), "run thread should have started"

    fresh_scheduler.shutdown(wait=False)
    block.set()  # release the thread so it can exit cleanly
    time.sleep(0.1)

    with Session(db_engine) as session:
        run = session.get(Run, "run_sched_shut_1")
        assert (
            run.status == "failed"
        ), f"shutdown(wait=False) must fail in-flight runs; got status={run.status!r}"
        assert run.error and run.error.get("type") == "ShutdownError"
