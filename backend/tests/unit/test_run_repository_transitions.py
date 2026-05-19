"""Run lifecycle transitions must keep planner_mode, started_at, duration_ms truthful.

Bugs being pinned:
  - RunRepository.create() never reads the parent Flow's planner_mode, so an
    agentic flow's Run rows come out with planner_mode='deterministic' (the
    model default). The /runs/{id} response surfaces this incorrectly.
  - mark_running() never sets started_at. The detail endpoint then computes
    duration from created_at, which includes queue + suspension time.
  - mark_completed() sets completed_at but never duration_ms. The persisted
    duration_ms column is left NULL even though the route can compute it.
"""

from sqlalchemy.orm import Session

from saz.db.models import Flow, Run
from saz.db.unit_of_work import UnitOfWork


def _make_agentic_flow(session: Session) -> str:
    flow = Flow(
        id="flow_agentic_meta",
        name="agentic_meta",
        definition={
            "schema_version": 1,
            "flow": {"name": "agentic_meta", "description": "test"},
            "workflow": {
                "planner_mode": "agentic",
                "steps": [],
            },
        },
    )
    session.add(flow)
    session.commit()
    return flow.id


def test_create_run_copies_planner_mode_from_flow(db_engine):
    """If the parent Flow is agentic, the Run row's planner_mode should be agentic."""
    with Session(db_engine) as session:
        flow_id = _make_agentic_flow(session)

    created_run_id: str
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            assert uow.runs is not None
            run = uow.runs.create(flow_id, payload={"x": 1})
            uow.commit()
            created_run_id = run.id

    with Session(db_engine) as session:
        run = session.get(Run, created_run_id)
        assert run is not None
        assert run.planner_mode == "agentic", (
            f"Run.planner_mode should reflect the parent Flow's planner_mode. "
            f"Got {run.planner_mode!r}. RunRepository.create() doesn't read it "
            f"from the Flow, so the model default ('deterministic') wins."
        )


def test_mark_running_sets_started_at(db_engine):
    """started_at distinguishes queue/wait time from actual execution time."""
    with Session(db_engine) as session:
        flow = Flow(
            id="flow_started_at",
            name="started_at_test",
            definition={
                "schema_version": 1,
                "flow": {"name": "started_at_test", "description": "test"},
                "workflow": {"planner_mode": "deterministic", "steps": []},
            },
        )
        session.add(flow)
        run = Run(
            id="run_started_at_1",
            flow_id="flow_started_at",
            status="queued",
            planner_mode="deterministic",
            payload={},
        )
        session.add(run)
        session.commit()

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            assert uow.runs is not None
            uow.runs.mark_running("run_started_at_1")
            uow.commit()

    with Session(db_engine) as session:
        run = session.get(Run, "run_started_at_1")
        assert run.status == "running"
        assert (
            run.started_at is not None
        ), "mark_running() must set started_at; today it only flips status."


def test_mark_completed_sets_duration_ms(db_engine):
    """duration_ms must be persisted, not only computed by the route on read."""
    from datetime import UTC, datetime, timedelta

    with Session(db_engine) as session:
        flow = Flow(
            id="flow_duration",
            name="duration_test",
            definition={
                "schema_version": 1,
                "flow": {"name": "duration_test", "description": "test"},
                "workflow": {"planner_mode": "deterministic", "steps": []},
            },
        )
        session.add(flow)
        run = Run(
            id="run_duration_1",
            flow_id="flow_duration",
            status="running",
            planner_mode="deterministic",
            payload={},
            started_at=datetime.now(UTC) - timedelta(seconds=2),
        )
        session.add(run)
        session.commit()

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            assert uow.runs is not None
            uow.runs.mark_completed("run_duration_1")
            uow.commit()

    with Session(db_engine) as session:
        run = session.get(Run, "run_duration_1")
        assert run.completed_at is not None, "sanity"
        assert run.duration_ms is not None, (
            "mark_completed() must populate Run.duration_ms — today it only "
            "sets completed_at, so the column stays NULL and the route has "
            "to recompute it from created_at on every read."
        )
        assert run.duration_ms > 0, f"duration_ms must be positive, got {run.duration_ms}"
