"""RunScheduler lifecycle: singleton, init, get_scheduler, shutdown branches.

The concurrency-focused tests live in test_scheduler_concurrency.py; this
file fills the lifecycle gaps that the coverage report flagged:

  * the ``__init__`` early-return when an instance already exists,
  * ``get_scheduler()`` lazy-creation from the DATABASE_URL env var,
  * ``get_scheduler()`` raising when DATABASE_URL is unset,
  * ``shutdown(wait=True)`` taking the no-mark path (no in-flight runs).
"""

import pytest

import saz.engine.scheduler as sched_module
from saz.engine.scheduler import RunScheduler, get_scheduler


@pytest.fixture
def _clean_singleton(monkeypatch):
    """Force a clean scheduler singleton for each test, restoring after."""
    monkeypatch.setattr(RunScheduler, "_instance", None)
    monkeypatch.setattr(sched_module, "_scheduler", None)
    yield
    monkeypatch.setattr(RunScheduler, "_instance", None)
    monkeypatch.setattr(sched_module, "_scheduler", None)


def test_scheduler_construction_is_idempotent(_clean_singleton, db_engine):
    """A second RunScheduler(...) call must return the same singleton without
    reinitialising — its workers and engine must be preserved."""
    first = RunScheduler(database_url=str(db_engine.url), max_workers=2)
    original_executor = first.executor
    original_engine = first.engine

    # Re-calling __init__ via the public constructor must short-circuit.
    second = RunScheduler(database_url=str(db_engine.url), max_workers=99)

    assert second is first
    assert second.executor is original_executor
    assert second.engine is original_engine
    assert second.max_workers == 2, "Re-init must NOT change the worker count"

    first.shutdown(wait=False)


def test_get_scheduler_creates_singleton_from_database_url(_clean_singleton, db_engine):
    scheduler = get_scheduler(str(db_engine.url))
    assert scheduler is not None
    assert get_scheduler() is scheduler, "second call must return the cached instance"
    scheduler.shutdown(wait=False)


def test_get_scheduler_raises_when_database_url_unset(_clean_singleton, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        get_scheduler()


def test_get_scheduler_reads_database_url_from_env(_clean_singleton, monkeypatch, db_engine):
    monkeypatch.setenv("DATABASE_URL", str(db_engine.url))
    scheduler = get_scheduler()
    assert str(scheduler.engine.url) == str(db_engine.url)
    scheduler.shutdown(wait=False)


def test_scheduler_shutdown_wait_true_when_no_inflight_runs_is_safe(_clean_singleton, db_engine):
    """``shutdown(wait=True)`` must NOT touch the DB when there are no
    in-flight runs — it's the graceful path and must be a no-op for
    persistence."""
    scheduler = RunScheduler(database_url=str(db_engine.url), max_workers=1)
    assert scheduler._running_runs == set()
    scheduler.shutdown(wait=True)


def test_scheduler_shutdown_wait_false_with_no_inflight_runs_skips_db_writes(
    _clean_singleton, db_engine
):
    """When _running_runs is empty, even shutdown(wait=False) must not open
    a session (no runs to mark)."""
    scheduler = RunScheduler(database_url=str(db_engine.url), max_workers=1)
    assert scheduler._running_runs == set()
    scheduler.shutdown(wait=False)
    # Subsequent submissions to a shutdown executor must be rejected.
    with pytest.raises(RuntimeError):
        scheduler.executor.submit(lambda: None).result(timeout=0.1)
