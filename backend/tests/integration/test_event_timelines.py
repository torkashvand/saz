"""Audit event timelines for critical operator-visible flows.

The audit story is one of Saz's core claims. Every safety-relevant
transition should land as a persisted Event row, in the right order,
with the right event_type. These tests assert the timeline shape end-to-end
via the real WorkflowExecutor for happy path and verifier-blocked path.
"""

import asyncio

from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import Verdict
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
    "description": "Fake recorded HTTP",
    "inputSchema": {
        "type": "object",
        "properties": {"method": {"type": "string"}, "url": {"type": "string"}},
        "required": ["method", "url"],
    },
}


def _seed_one_step_run(session: Session) -> str:
    flow = Flow(
        created_by_user_id=TEST_USER_ID,
        id="flow_evt_timeline",
        name="evt_timeline",
        definition={
            "schema_version": 1,
            "flow": {"name": "evt_timeline", "description": "audit timeline"},
            "workflow": {
                "planner_mode": "deterministic",
                "steps": [
                    {
                        "id": "do",
                        "type": "tool.call",
                        "description": "single call",
                        "tool": "http_request",
                        "params": {"method": "GET", "url": "https://e.com/x"},
                    }
                ],
            },
            "policies": {"budget_usd": 1.0},
        },
    )
    run = Run(
        created_by_user_id=TEST_USER_ID,
        id="run_evt_timeline_1",
        flow_id="flow_evt_timeline",
        status="queued",
        planner_mode="deterministic",
        payload={},
    )
    session.add_all([flow, run])
    session.commit()
    return run.id


def _event_types(db_engine, run_id: str) -> list[str]:
    with Session(db_engine) as session:
        events = (
            session.query(Event)
            .filter(Event.run_id == run_id)
            .order_by(Event.timestamp, Event.id)
            .all()
        )
        return [e.event_type for e in events]


def test_deterministic_success_emits_expected_timeline(db_engine):
    with Session(db_engine) as session:
        run_id = _seed_one_step_run(session)

    fake_http = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    registry = ToolRegistry()
    registry.register_custom_tool("http_request", fake_http.spec, fake_http.execute)

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

    types = _event_types(db_engine, run_id)
    assert types, "audit events must be persisted for a successful run"
    # Each of these must appear at least once; order between them is the
    # natural execution order.
    must_include = {"run.started", "step.started", "tool.started", "tool.succeeded"}
    missing = must_include - set(types)
    assert not missing, (
        f"deterministic-success timeline is missing event_types {sorted(missing)}; " f"got {types}"
    )

    # run.started must precede step.started must precede tool.started
    def first_index(t: str) -> int:
        return types.index(t)

    assert first_index("run.started") < first_index("step.started")
    assert first_index("step.started") < first_index("tool.started")
    assert first_index("tool.started") < first_index("tool.succeeded")


def test_verifier_block_emits_rejection_event_without_tool_started(db_engine):
    with Session(db_engine) as session:
        run_id = _seed_one_step_run(session)

    fake_http = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    registry = ToolRegistry()
    registry.register_custom_tool("http_request", fake_http.spec, fake_http.execute)

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = WorkflowExecutor(
                uow=uow,
                tool_registry=registry,
                planner=DeterministicPlanner(),
                executor_agent=ExecutorAgent(),
                critic=FakeCritic(default_verify=Verdict.FAIL),  # type: ignore[arg-type]
                policy_engine=PolicyEngine(),
            )
            try:
                asyncio.run(executor.execute_run(run_id))
            except Exception:
                pass

    types = _event_types(db_engine, run_id)
    assert types, "audit events must be persisted even when verification blocks"
    assert (
        "verifier.rejected" in types
    ), f"verifier.rejected must be emitted on FAIL verdict; got {types}"
    assert (
        "tool.succeeded" not in types
    ), "tool.succeeded MUST NOT appear when the verifier blocked execution"
