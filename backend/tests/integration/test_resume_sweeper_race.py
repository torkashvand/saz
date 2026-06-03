"""Resume and the suspension sweeper must not race into resurrection.

The sweeper fails timed-out suspensions with an atomic
``UPDATE ... WHERE status='suspended'`` (mark_failed_if_suspended). The resume
path must use the same guard (mark_queued_if_suspended) so that whichever
transition commits first wins, and the loser is a no-op. A last-writer-wins
read-then-write would let resume resurrect an already-failed (timed-out) run.
"""

import pytest
from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step
from saz.db.unit_of_work import UnitOfWork
from saz.services.run_service import RunService
from tests.conftest import TEST_USER_ID


def _seed_suspended(session: Session) -> str:
    session.add(
        Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_race",
            name="race",
            definition={"workflow": {"planner_mode": "deterministic"}},
        )
    )
    session.add(
        Run(
            created_by_user_id=TEST_USER_ID,
            id="run_race",
            flow_id="flow_race",
            status="suspended",
            planner_mode="deterministic",
            payload={},
            error={"type": "HumanApprovalRequired", "step_id": "approve", "callback_id": "cb"},
        )
    )
    session.add(
        Step(
            id="step_race",
            run_id="run_race",
            number=0,
            name="approve",
            step_type="human.approval",
            status="suspended",
            attempt=1,
        )
    )
    session.commit()
    return "run_race"


def test_sweeper_wins_resume_cannot_resurrect(db_engine):
    """Sweeper fails the run first; a subsequent resume must be a no-op."""
    with Session(db_engine) as session:
        _seed_suspended(session)

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        # Sweeper wins the race.
        assert uow.runs.mark_failed_if_suspended(
            "run_race", {"type": "SuspensionTimeout", "message": "timed out"}
        )
        uow.commit()

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        with pytest.raises(ValueError, match="not suspended"):
            RunService(uow).resume_run("run_race", resume_data={"approved": True})

    with Session(db_engine) as session:
        run = session.get(Run, "run_race")
        assert run.status == "failed", "timed-out run must not be resurrected"
        assert run.error["type"] == "SuspensionTimeout"


def test_resume_wins_sweeper_cannot_fail(db_engine):
    """Resume requeues the run first; a subsequent sweeper pass must be a no-op."""
    with Session(db_engine) as session:
        _seed_suspended(session)

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        RunService(uow).resume_run("run_race", resume_data={"approved": True})

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        # Sweeper loses: run is already queued, atomic guard matches no rows.
        assert not uow.runs.mark_failed_if_suspended(
            "run_race", {"type": "SuspensionTimeout", "message": "timed out"}
        )
        uow.commit()

    with Session(db_engine) as session:
        run = session.get(Run, "run_race")
        assert run.status == "queued", "resumed run must not be failed by the sweeper"
