"""SuspensionSweeper lifecycle and constructor validation tests.

Functional sweeping is covered in tests/integration/test_suspension_sweeper.py.
This module pins:

  * APScheduler ``start()`` / ``stop()`` idempotency,
  * constructor argument validation,
  * ``sweep_once`` no-op when there are no expired suspensions,
  * the module-level singleton (``get_suspension_sweeper``) including the
    env-driven DATABASE_URL path and the missing-URL ValueError.
"""

from __future__ import annotations

import pytest

import saz.engine.suspension_sweeper as sweeper_module
from saz.engine.suspension_sweeper import (
    SuspensionSweeper,
    get_suspension_sweeper,
    reset_suspension_sweeper_for_tests,
)


@pytest.fixture
def clean_sweeper_singleton():
    reset_suspension_sweeper_for_tests()
    yield
    reset_suspension_sweeper_for_tests()


# --------------------------- constructor validation ---------------------------


def test_suspension_sweeper_rejects_non_positive_interval(db_engine) -> None:
    with pytest.raises(ValueError, match="interval_seconds"):
        SuspensionSweeper(
            database_url=str(db_engine.url),
            interval_seconds=0,
            engine=db_engine,
        )


def test_suspension_sweeper_rejects_non_positive_batch_limit(db_engine) -> None:
    with pytest.raises(ValueError, match="batch_limit"):
        SuspensionSweeper(
            database_url=str(db_engine.url),
            batch_limit=0,
            engine=db_engine,
        )


# --------------------------- start / stop lifecycle ---------------------------


def test_suspension_sweeper_start_then_stop_lifecycle(db_engine) -> None:
    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        interval_seconds=60.0,
        engine=db_engine,
    )

    assert sweeper._scheduler is None
    sweeper.start()
    assert sweeper._scheduler is not None
    assert sweeper._scheduler.running is True

    sweeper.stop()
    assert sweeper._scheduler is None


def test_suspension_sweeper_start_is_idempotent(db_engine) -> None:
    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        interval_seconds=60.0,
        engine=db_engine,
    )
    try:
        sweeper.start()
        first = sweeper._scheduler
        sweeper.start()  # second call must short-circuit
        assert (
            sweeper._scheduler is first
        ), "Second start() must not replace the live APScheduler instance"
    finally:
        sweeper.stop()


def test_suspension_sweeper_stop_without_start_is_safe(db_engine) -> None:
    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        engine=db_engine,
    )
    # Has never been started; must not raise.
    sweeper.stop()
    assert sweeper._scheduler is None


def test_suspension_sweeper_stop_is_idempotent(db_engine) -> None:
    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        interval_seconds=60.0,
        engine=db_engine,
    )
    sweeper.start()
    sweeper.stop()
    # Calling stop a second time on an already-stopped sweeper must not raise.
    sweeper.stop()
    assert sweeper._scheduler is None


# --------------------------- sweep_once no-op ---------------------------


def test_sweep_once_returns_zero_when_no_suspended_runs(db_engine) -> None:
    """Empty DB → no expired runs → 0 returned, no errors."""
    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        engine=db_engine,
    )
    assert sweeper.sweep_once() == 0


# --------------------------- module-level singleton ---------------------------


def test_get_suspension_sweeper_creates_singleton(clean_sweeper_singleton, db_engine) -> None:
    a = get_suspension_sweeper(str(db_engine.url))
    b = get_suspension_sweeper(str(db_engine.url))
    assert a is b


def test_get_suspension_sweeper_reads_env_when_url_omitted(
    clean_sweeper_singleton, db_engine, monkeypatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", str(db_engine.url))
    sweeper = get_suspension_sweeper()
    assert sweeper is not None
    assert sweeper._database_url == str(db_engine.url)


def test_get_suspension_sweeper_raises_when_no_url_available(
    clean_sweeper_singleton, monkeypatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        get_suspension_sweeper()


def test_get_suspension_sweeper_forwards_optional_kwargs(
    clean_sweeper_singleton, db_engine
) -> None:
    sweeper = get_suspension_sweeper(
        str(db_engine.url),
        interval_seconds=42.0,
        batch_limit=7,
    )
    assert sweeper._interval_seconds == 42.0
    assert sweeper._batch_limit == 7


def test_reset_suspension_sweeper_for_tests_clears_singleton(
    clean_sweeper_singleton, db_engine
) -> None:
    sweeper_module._sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        engine=db_engine,
    )
    sweeper_module._sweeper.start()
    reset_suspension_sweeper_for_tests()
    assert sweeper_module._sweeper is None
