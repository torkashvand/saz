"""Acceptance: safety transitions are emitted as first-class audit events.

Before the hardening pass, policy blocks left only a Step.policy_flags field,
artifact creation produced no event, and the post-execution critique was never
emitted. These transitions must now be queryable in the event timeline.
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


def _event_types(db_engine, run_id: str) -> list[str]:
    with Session(db_engine) as session:
        rows = (
            session.query(Event)
            .filter(Event.run_id == run_id)
            .order_by(Event.timestamp, Event.id)
            .all()
        )
        return [r.event_type for r in rows]


def _seed(session, flow_id, run_id, definition):
    session.add_all(
        [
            Flow(created_by_user_id=TEST_USER_ID, id=flow_id, name=flow_id, definition=definition),
            Run(
                created_by_user_id=TEST_USER_ID,
                id=run_id,
                flow_id=flow_id,
                status="queued",
                planner_mode="deterministic",
                payload={},
            ),
        ]
    )
    session.commit()


def _run(db_engine, run_id, registry, critic=None):
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = WorkflowExecutor(
                uow=uow,
                tool_registry=registry,
                planner=DeterministicPlanner(),
                executor_agent=ExecutorAgent(),
                critic=critic or FakeCritic(),  # type: ignore[arg-type]
                policy_engine=PolicyEngine(),
            )
            try:
                asyncio.run(executor.execute_run(run_id))
            except Exception:
                pass


HTTP_SPEC = {
    "name": "http_request",
    "description": "fake",
    "inputSchema": {
        "type": "object",
        "properties": {
            "method": {"type": "string"},
            "url": {"type": "string"},
            "body": {"type": "object"},
        },
        "required": ["method", "url"],
    },
}

ARTIFACT_SPEC = {
    "name": "artifact.store",
    "description": "fake artifact store",
    "inputSchema": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "content": {"type": "object"}},
        "required": ["name", "content"],
    },
}


def test_policy_block_emits_policy_blocked_event(db_engine):
    definition = {
        "schema_version": 1,
        "flow": {"name": "blk", "description": "pii block"},
        "workflow": {
            "planner_mode": "deterministic",
            "steps": [
                {
                    "id": "leak",
                    "type": "tool.call",
                    "description": "leak pii",
                    "tool": "http_request",
                    "params": {
                        "method": "POST",
                        "url": "https://api.example.com/x",
                        "body": {"comment": "reach me at user@example.com"},
                    },
                }
            ],
        },
        "policies": {"budget_usd": 1.0, "pii": {"allow": False}},
    }
    with Session(db_engine) as session:
        _seed(session, "flow_evt_blk", "run_evt_blk", definition)
    registry = ToolRegistry()
    tool = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    registry.register_custom_tool("http_request", tool.spec, tool.execute)

    _run(db_engine, "run_evt_blk", registry)

    types = _event_types(db_engine, "run_evt_blk")
    assert "policy.blocked" in types, types
    assert tool.call_count == 0


def test_artifact_and_critique_events_emitted(db_engine):
    definition = {
        "schema_version": 1,
        "flow": {"name": "art", "description": "artifact"},
        "workflow": {
            "planner_mode": "deterministic",
            "steps": [
                {
                    "id": "save",
                    "type": "artifact.store",
                    "description": "store an artifact",
                    "tool": "artifact.store",
                    "params": {"name": "report", "content": {"value": "ok"}},
                }
            ],
        },
        "policies": {"budget_usd": 1.0},
    }
    with Session(db_engine) as session:
        _seed(session, "flow_evt_art", "run_evt_art", definition)
    registry = ToolRegistry()
    art = RecordingTool(
        "artifact.store",
        response={
            "artifact_id": "art-123",
            "name": "report",
            "storage_path": "/tmp/saz/report.json",
            "content_type": "json",
        },
        spec=ARTIFACT_SPEC,
    )
    registry.register_custom_tool("artifact.store", art.spec, art.execute)

    _run(db_engine, "run_evt_art", registry)

    types = _event_types(db_engine, "run_evt_art")
    assert "artifact.created" in types, types
    assert "critique.completed" in types, types
    assert "run.completed" in types, types


def _one_http_step(flow_id):
    return {
        "schema_version": 1,
        "flow": {"name": flow_id, "description": "x"},
        "workflow": {
            "planner_mode": "deterministic",
            "steps": [
                {
                    "id": "do",
                    "type": "tool.call",
                    "description": "call",
                    "tool": "http_request",
                    "params": {"method": "GET", "url": "https://api.example.com/x"},
                }
            ],
        },
        "policies": {"budget_usd": 1.0},
    }


def test_budget_exhaustion_emits_event(db_engine):
    with Session(db_engine) as session:
        _seed(session, "flow_evt_bud", "run_evt_bud", _one_http_step("flow_evt_bud"))
    registry = ToolRegistry()
    tool = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    registry.register_custom_tool("http_request", tool.spec, tool.execute)

    # max_steps=0 trips the per-step budget gate before the first step runs.
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = WorkflowExecutor(
                uow=uow,
                tool_registry=registry,
                planner=DeterministicPlanner(),
                executor_agent=ExecutorAgent(),
                critic=FakeCritic(),  # type: ignore[arg-type]
                policy_engine=PolicyEngine(budget_tracker=_zero_step_budget()),
            )
            try:
                asyncio.run(executor.execute_run("run_evt_bud"))
            except Exception:
                pass

    types = _event_types(db_engine, "run_evt_bud")
    assert "policy.budget.exhausted" in types, types
    assert tool.call_count == 0


def test_rate_limit_emits_event(db_engine):
    with Session(db_engine) as session:
        _seed(session, "flow_evt_rl", "run_evt_rl", _one_http_step("flow_evt_rl"))
    registry = ToolRegistry()
    tool = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    registry.register_custom_tool("http_request", tool.spec, tool.execute)

    pe = PolicyEngine()
    pe.rate_limiter.per_tool_rpm = {"http_request": 0}  # block immediately
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = WorkflowExecutor(
                uow=uow,
                tool_registry=registry,
                planner=DeterministicPlanner(),
                executor_agent=ExecutorAgent(),
                critic=FakeCritic(),  # type: ignore[arg-type]
                policy_engine=pe,
            )
            try:
                asyncio.run(executor.execute_run("run_evt_rl"))
            except Exception:
                pass

    types = _event_types(db_engine, "run_evt_rl")
    assert "policy.rate_limited" in types, types
    assert tool.call_count == 0


def _zero_step_budget():
    from saz.policies.budget_tracker import BudgetTracker

    return BudgetTracker(max_tokens=100000, max_cost_usd=10.0, max_steps=0)


def test_human_approval_emits_step_suspended(db_engine):
    definition = {
        "schema_version": 1,
        "flow": {"name": "appr", "description": "approval"},
        "workflow": {
            "planner_mode": "deterministic",
            "steps": [
                {
                    "id": "gate",
                    "type": "human.approval",
                    "description": "approve me",
                    "params": {"message": "ok?"},
                }
            ],
        },
        "policies": {"budget_usd": 1.0},
    }
    with Session(db_engine) as session:
        _seed(session, "flow_evt_appr", "run_evt_appr", definition)

    _run(db_engine, "run_evt_appr", ToolRegistry())

    types = _event_types(db_engine, "run_evt_appr")
    assert "step.suspended" in types, types
    assert "approval.requested" in types, types
    assert "run.suspended" in types, types
