"""Suspension-timeout vs resume race must not corrupt run status.

The sweeper now fails a run via an atomic ``UPDATE ... WHERE status='suspended'``
so a concurrent resume that already moved the run to ``queued`` cannot be
overwritten with ``failed`` using stale in-memory status.
"""

from sqlalchemy.orm import Session

from saz.db.models import Flow, Run
from saz.db.unit_of_work import UnitOfWork
from tests.conftest import TEST_USER_ID

TIMEOUT_ERR = {
    "type": "SuspensionTimeout",
    "message": "timed out",
    "step_id": "gate",
}


def _seed_suspended(session, run_id="run_race"):
    session.add_all(
        [
            Flow(
                created_by_user_id=TEST_USER_ID,
                id=f"flow_{run_id}",
                name=f"flow_{run_id}",
                definition={"workflow": {"planner_mode": "deterministic"}},
            ),
            Run(
                created_by_user_id=TEST_USER_ID,
                id=run_id,
                flow_id=f"flow_{run_id}",
                status="suspended",
                planner_mode="deterministic",
                error={"type": "HumanApprovalRequired", "step_id": "gate"},
            ),
        ]
    )
    session.commit()


def test_mark_failed_if_suspended_applies_when_suspended(db_engine):
    with Session(db_engine) as session:
        _seed_suspended(session, "run_race_1")
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            assert uow.runs is not None
            assert uow.runs.mark_failed_if_suspended("run_race_1", TIMEOUT_ERR) is True
            uow.commit()
    with Session(db_engine) as session:
        assert session.get(Run, "run_race_1").status == "failed"


def test_resume_before_sweeper_wins(db_engine):
    """Resume commits 'queued' in another session AFTER the sweeper loaded the
    run; the atomic guard must see committed state and refuse to fail it."""
    with Session(db_engine) as session:
        _seed_suspended(session, "run_race_2")

    # Sweeper session loads the run (identity map now caches status=suspended).
    sweeper_session = Session(db_engine)
    sweeper_uow = UnitOfWork(sweeper_session).__enter__()
    assert sweeper_uow.runs is not None
    loaded = sweeper_uow.runs.get("run_race_2")
    assert loaded.status == "suspended"  # stale snapshot the bug relied on

    # A concurrent resume commits queued in a separate session.
    with Session(db_engine) as other:
        run = other.get(Run, "run_race_2")
        run.status = "queued"
        run.error = None
        other.commit()

    # Sweeper tries to fail it using its stale in-memory view.
    applied = sweeper_uow.runs.mark_failed_if_suspended("run_race_2", TIMEOUT_ERR)
    sweeper_uow.commit()
    sweeper_session.close()

    assert applied is False, "sweeper must not fail a run that was resumed"
    with Session(db_engine) as session:
        assert session.get(Run, "run_race_2").status == "queued"
