"""Unit tests for StepRepository helpers.

These cover the lookup helpers that the executor and webhook callback
handler rely on:

  * ``get_first_failed_for_run`` — must return failed steps from the
    *latest* attempt only (so a successful retry does not re-surface as
    a failure to the UI).
  * ``get_first_suspended_for_run`` — the single suspended step for a run.
  * ``get_by_name`` / ``get_max_attempt`` — attempt counter math.
  * status-transition mutators with structured-error persistence.
"""

import pytest
from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step
from saz.repositories.write.step_repository import StepRepository


@pytest.fixture
def session(db_engine):
    with Session(db_engine) as s:
        yield s


@pytest.fixture
def run_id(session: Session) -> str:
    flow = Flow(
        id="flow_step_repo",
        name="step_repo_flow",
        definition={"workflow": {"steps": []}},
    )
    run = Run(
        id="run_step_repo_1",
        flow_id="flow_step_repo",
        status="running",
        planner_mode="deterministic",
        payload={},
    )
    session.add_all([flow, run])
    session.commit()
    return run.id


# --------------------------- mutators ---------------------------


def test_append_persists_step_with_defaults(session: Session, run_id: str) -> None:
    repo = StepRepository(session)
    step = repo.append(run_id=run_id, number=0, name="extract", step_type="ai.extract")
    session.commit()

    refetched = session.get(Step, step.id)
    assert refetched is not None
    assert refetched.run_id == run_id
    assert refetched.name == "extract"
    assert refetched.status == "queued"
    assert refetched.attempt == 1
    assert refetched.retry_count == 0


def test_mark_running_then_completed_records_duration(session: Session, run_id: str) -> None:
    repo = StepRepository(session)
    step = repo.append(run_id=run_id, number=0, name="x", step_type="ai.extract")
    session.commit()

    repo.mark_running(step.id)
    session.commit()
    assert step.status == "running"
    assert step.start_ts is not None

    repo.mark_completed(step.id)
    session.commit()
    assert step.status == "completed"
    assert step.end_ts is not None
    assert step.duration_ms is not None
    assert step.duration_ms >= 0


def test_mark_failed_persists_structured_error(session: Session, run_id: str) -> None:
    repo = StepRepository(session)
    step = repo.append(run_id=run_id, number=0, name="x", step_type="tool.call")
    repo.mark_running(step.id)
    session.commit()

    err = {
        "message": "bad input",
        "type": "ValueError",
        "category": "validation",
        "retryable": False,
    }
    repo.mark_failed(step.id, err)
    session.commit()

    assert step.status == "failed"
    assert step.error == err
    assert step.end_ts is not None
    assert step.duration_ms is not None


def test_mark_suspended_does_not_set_end_ts(session: Session, run_id: str) -> None:
    repo = StepRepository(session)
    step = repo.append(run_id=run_id, number=0, name="approve", step_type="human.approval")
    repo.mark_running(step.id)
    session.commit()

    repo.mark_suspended(step.id)
    session.commit()
    assert step.status == "suspended"
    assert (
        step.end_ts is None
    ), "Suspended steps must NOT receive an end timestamp — they're still in flight."


def test_increment_retry_bumps_counter(session: Session, run_id: str) -> None:
    repo = StepRepository(session)
    step = repo.append(run_id=run_id, number=0, name="x", step_type="tool.call")
    session.commit()
    assert step.retry_count == 0
    repo.increment_retry(step.id)
    repo.increment_retry(step.id)
    session.commit()
    assert step.retry_count == 2


# --------------------------- queries ---------------------------


def test_get_last_for_run_returns_highest_number(session: Session, run_id: str) -> None:
    repo = StepRepository(session)
    repo.append(run_id=run_id, number=0, name="a", step_type="ai.extract")
    repo.append(run_id=run_id, number=1, name="b", step_type="tool.call")
    repo.append(run_id=run_id, number=2, name="c", step_type="artifact.store")
    session.commit()

    last = repo.get_last_for_run(run_id)
    assert last is not None
    assert last.number == 2
    assert last.name == "c"


def test_get_by_name_returns_latest_attempt(session: Session, run_id: str) -> None:
    repo = StepRepository(session)
    repo.append(run_id=run_id, number=0, name="extract", step_type="ai.extract", attempt=1)
    repo.append(run_id=run_id, number=0, name="extract", step_type="ai.extract", attempt=2)
    repo.append(run_id=run_id, number=0, name="extract", step_type="ai.extract", attempt=3)
    session.commit()

    step = repo.get_by_name(run_id, "extract")
    assert step is not None
    assert step.attempt == 3


def test_get_by_name_returns_none_for_unknown(session: Session, run_id: str) -> None:
    repo = StepRepository(session)
    repo.append(run_id=run_id, number=0, name="other", step_type="ai.extract")
    session.commit()
    assert repo.get_by_name(run_id, "missing") is None


def test_get_max_attempt_returns_zero_when_no_steps(session: Session, run_id: str) -> None:
    repo = StepRepository(session)
    assert repo.get_max_attempt(run_id, "never") == 0


def test_get_max_attempt_returns_highest_attempt(session: Session, run_id: str) -> None:
    repo = StepRepository(session)
    repo.append(run_id=run_id, number=0, name="x", step_type="tool.call", attempt=1)
    repo.append(run_id=run_id, number=0, name="x", step_type="tool.call", attempt=4)
    repo.append(run_id=run_id, number=0, name="x", step_type="tool.call", attempt=2)
    session.commit()
    assert repo.get_max_attempt(run_id, "x") == 4


def test_get_first_suspended_for_run_returns_suspended(session: Session, run_id: str) -> None:
    repo = StepRepository(session)
    a = repo.append(run_id=run_id, number=0, name="a", step_type="ai.extract")
    b = repo.append(run_id=run_id, number=1, name="b", step_type="human.approval")
    repo.mark_completed(a.id)
    repo.mark_suspended(b.id)
    session.commit()

    susp = repo.get_first_suspended_for_run(run_id)
    assert susp is not None
    assert susp.id == b.id


def test_get_first_suspended_returns_none_when_no_suspended_step(
    session: Session, run_id: str
) -> None:
    repo = StepRepository(session)
    a = repo.append(run_id=run_id, number=0, name="a", step_type="ai.extract")
    repo.mark_completed(a.id)
    session.commit()
    assert repo.get_first_suspended_for_run(run_id) is None


def test_get_first_failed_excludes_old_attempts_after_successful_retry(
    session: Session, run_id: str
) -> None:
    """A successful retry must hide the historical failed attempt — the
    UI's 'first failed step' panel must not point at a stale failure."""
    repo = StepRepository(session)
    failed_first = repo.append(
        run_id=run_id, number=0, name="boom", step_type="tool.call", attempt=1
    )
    repo.mark_running(failed_first.id)
    repo.mark_failed(failed_first.id, {"message": "first try"})

    succeeded_retry = repo.append(
        run_id=run_id, number=0, name="boom", step_type="tool.call", attempt=2
    )
    repo.mark_running(succeeded_retry.id)
    repo.mark_completed(succeeded_retry.id)
    session.commit()

    assert repo.get_first_failed_for_run(run_id) is None


def test_get_first_failed_returns_latest_failed_attempt(session: Session, run_id: str) -> None:
    """If the *latest* attempt failed, the panel must return that one — not
    the earlier failure of the same step nor an unrelated successful step."""
    repo = StepRepository(session)
    ok = repo.append(run_id=run_id, number=0, name="ok", step_type="ai.extract", attempt=1)
    failed_v1 = repo.append(run_id=run_id, number=1, name="boom", step_type="tool.call", attempt=1)
    failed_v2 = repo.append(run_id=run_id, number=1, name="boom", step_type="tool.call", attempt=2)
    repo.mark_running(ok.id)
    repo.mark_completed(ok.id)
    repo.mark_running(failed_v1.id)
    repo.mark_failed(failed_v1.id, {"message": "v1"})
    repo.mark_running(failed_v2.id)
    repo.mark_failed(failed_v2.id, {"message": "v2"})
    session.commit()

    result = repo.get_first_failed_for_run(run_id)
    assert result is not None
    assert result.id == failed_v2.id
    assert result.error == {"message": "v2"}


def test_get_latest_attempts_for_run_returns_one_per_name(session: Session, run_id: str) -> None:
    repo = StepRepository(session)
    repo.append(run_id=run_id, number=0, name="a", step_type="ai.extract", attempt=1)
    repo.append(run_id=run_id, number=0, name="a", step_type="ai.extract", attempt=2)
    repo.append(run_id=run_id, number=1, name="b", step_type="tool.call", attempt=1)
    session.commit()

    latest = repo.get_latest_attempts_for_run(run_id)
    assert len(latest) == 2
    by_name = {s.name: s for s in latest}
    assert by_name["a"].attempt == 2
    assert by_name["b"].attempt == 1
