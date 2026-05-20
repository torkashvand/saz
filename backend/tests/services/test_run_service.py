"""RunService unit tests — preconditions for retry, resume, lifecycle."""

import pytest
from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step
from saz.db.unit_of_work import UnitOfWork
from saz.services.run_service import RunService
from tests.conftest import TEST_USER_ID


def _seed_flow(session: Session, planner_mode: str = "deterministic") -> str:
    flow = Flow(
        created_by_user_id=TEST_USER_ID,
        id="flow_svc_run",
        name="svc_run",
        definition={
            "schema_version": 1,
            "flow": {"name": "svc_run", "description": "test"},
            "workflow": {
                "planner_mode": planner_mode,
                "steps": [
                    {
                        "id": "do",
                        "type": "tool.call",
                        "description": "Do something",
                        "tool": "http_request",
                        "params": {"method": "GET", "url": "https://e.com"},
                    }
                ]
                if planner_mode == "deterministic"
                else [],
            },
        },
    )
    session.add(flow)
    session.commit()
    return flow.id


def _seed_failed_run_with_failed_step(session: Session, flow_id: str) -> str:
    run = Run(
        created_by_user_id=TEST_USER_ID,
        id="run_svc_run_failed",
        flow_id=flow_id,
        status="failed",
        planner_mode="deterministic",
        payload={},
        error={"type": "Test", "message": "boom"},
    )
    session.add(run)
    step = Step(
        id="step_svc_run_failed",
        run_id="run_svc_run_failed",
        number=0,
        name="do",
        step_type="tool.call",
        status="failed",
        attempt=1,
        error={"type": "Test", "message": "boom"},
    )
    session.add(step)
    session.commit()
    return run.id


def test_create_run_returns_id_and_persists(db_engine):
    with Session(db_engine) as session:
        flow_id = _seed_flow(session)

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            service = RunService(uow)
            run_id = service.create(flow_id, payload={"k": "v"}, created_by_user_id=TEST_USER_ID)
            assert run_id

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.flow_id == flow_id
        assert run.status == "queued"
        assert run.payload == {"k": "v"}


def test_create_rejects_unknown_flow(db_engine):
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            with pytest.raises(ValueError, match="Flow not found"):
                RunService(uow).create(
                    "flow_does_not_exist", payload={}, created_by_user_id=TEST_USER_ID
                )


def test_retry_only_allowed_on_failed_or_error(db_engine):
    """retry() must reject non-terminal-failure runs."""
    with Session(db_engine) as session:
        flow_id = _seed_flow(session)
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_svc_run_running",
            flow_id=flow_id,
            status="running",
            planner_mode="deterministic",
            payload={},
        )
        session.add(run)
        session.commit()

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            with pytest.raises(ValueError, match="Can only retry failed runs"):
                RunService(uow).retry("run_svc_run_running")


def test_retry_resets_failed_run_to_queued(db_engine):
    with Session(db_engine) as session:
        flow_id = _seed_flow(session)
        _seed_failed_run_with_failed_step(session, flow_id)

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            RunService(uow).retry("run_svc_run_failed")

    with Session(db_engine) as session:
        run = session.get(Run, "run_svc_run_failed")
        assert run.status == "queued"
        assert run.error is None


def test_resume_rejects_non_suspended_run(db_engine):
    with Session(db_engine) as session:
        flow_id = _seed_flow(session)
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_svc_run_completed",
            flow_id=flow_id,
            status="completed",
            planner_mode="deterministic",
            payload={},
        )
        session.add(run)
        session.commit()

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            with pytest.raises(ValueError, match="not suspended"):
                RunService(uow).resume_run("run_svc_run_completed", resume_data={"approved": True})
