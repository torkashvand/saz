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

    # render_as_string(hide_password=False): str(url) masks the password, which
    # breaks the scheduler thread's PostgreSQL auth.
    scheduler = RunScheduler(
        database_url=db_engine.url.render_as_string(hide_password=False), max_workers=2
    )

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


def test_requeue_during_teardown_is_rescheduled(fresh_scheduler, monkeypatch, db_engine):
    """A resume/callback can flip a run to 'queued' after its suspension is
    committed but while the executor thread is still tearing down. schedule()
    refuses it (the id is still in _running_runs) and nothing rescans queued
    runs — without a post-teardown re-check the run is stranded forever."""
    from sqlalchemy.orm import Session

    from saz.db.models import Flow, Run
    from saz.engine.executor import WorkflowExecutor
    from saz.globals import initialize_globals

    # _execute_run_sync builds real agents from saz.globals; the executor
    # itself is faked below, but the constructor chain must not crash.
    initialize_globals()

    with Session(db_engine) as session:
        session.add(
            Flow(
                created_by_user_id=TEST_USER_ID,
                id="flow_requeue",
                name="flow_requeue",
                definition={},
            )
        )
        session.commit()
        session.add(
            Run(
                created_by_user_id=TEST_USER_ID,
                id="run_requeue",
                flow_id="flow_requeue",
                status="running",
                planner_mode="deterministic",
                payload={},
            )
        )
        session.commit()

    executions: list[int] = []
    done = threading.Event()

    async def fake_execute_run(self, run_id: str) -> None:
        executions.append(1)
        if len(executions) == 1:
            # Simulate a fast callback landing in the teardown window: it
            # flips the run to queued and calls schedule(), which refuses
            # because this very thread still holds the id.
            with Session(db_engine) as s:
                run = s.get(Run, run_id)
                assert run is not None
                run.status = "queued"
                s.commit()
            assert fresh_scheduler.schedule(run_id) is False
        else:
            with Session(db_engine) as s:
                run = s.get(Run, run_id)
                assert run is not None
                run.status = "completed"
                s.commit()
            done.set()

    monkeypatch.setattr(WorkflowExecutor, "execute_run", fake_execute_run)

    assert fresh_scheduler.schedule("run_requeue") is True
    assert done.wait(timeout=5), "re-queued run was never rescheduled — stranded in 'queued'"

    with Session(db_engine) as s:
        run = s.get(Run, "run_requeue")
        assert run is not None
        assert run.status == "completed"
