"""Event sequencing: persisted events carry a monotonic per-run seq and the
read query returns them in deterministic order.

This is what lets the live overlay reconcile with canonical DB state instead
of relying on timestamp ties.
"""

import asyncio

from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.db.models import Event, Flow, Run
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.tools.registry import ToolRegistry
from tests.conftest import TEST_USER_ID
from tests.fakes.critic import FakeCritic
from tests.fakes.tools import RecordingTool

HTTP_SPEC = {
    "name": "http_request",
    "description": "fake",
    "input_schema": {
        "type": "object",
        "properties": {"method": {"type": "string"}, "url": {"type": "string"}},
        "required": ["method", "url"],
    },
}


def _seed_two_step_run(session, run_id="run_seq_1"):
    step = {
        "id": "s",
        "type": "tool.call",
        "description": "call",
        "tool": "http_request",
        "params": {"method": "GET", "url": "https://api.example.com/x"},
    }
    flow = Flow(
        created_by_user_id=TEST_USER_ID,
        id=f"flow_{run_id}",
        name=f"flow_{run_id}",
        definition={
            "schema_version": 1,
            "flow": {"name": run_id, "description": "seq"},
            "workflow": {
                "planner_mode": "deterministic",
                "steps": [{**step, "id": "s1"}, {**step, "id": "s2"}],
            },
            "policies": {"budget_usd": 5.0},
        },
    )
    run = Run(
        created_by_user_id=TEST_USER_ID,
        id=run_id,
        flow_id=f"flow_{run_id}",
        status="queued",
        planner_mode="deterministic",
        payload={},
    )
    session.add_all([flow, run])
    session.commit()
    return run_id


def test_events_get_monotonic_seq_and_ordered_query(db_engine):
    with Session(db_engine) as session:
        run_id = _seed_two_step_run(session)

    registry = ToolRegistry()
    tool = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    registry.register_custom_tool("http_request", tool.spec, tool.execute)
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = WorkflowExecutor(
                uow=uow,
                tool_registry=registry,
                planner=DeterministicPlanner(),
                executor_agent=ExecutorAgent(),
                critic=FakeCritic(),  # type: ignore[arg-type]
                policy_engine=PolicyEngine(),
            )
            asyncio.run(executor.execute_run(run_id))

    # All persisted events have a seq, strictly increasing in insertion order.
    with Session(db_engine) as session:
        rows = session.query(Event).filter(Event.run_id == run_id).order_by(Event.seq.asc()).all()
        seqs = [r.seq for r in rows]
        assert all(s is not None for s in seqs), seqs
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs), f"seq must be unique per run: {seqs}"
        assert seqs[0] == 1

    # The read query returns events in deterministic (timestamp, seq) order.
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            assert uow.event_queries is not None
            events, _ = uow.event_queries.get_by_run(run_id, limit=500)
            ordered_seqs = [e.seq for e in events]
            assert ordered_seqs == sorted(ordered_seqs), ordered_seqs
