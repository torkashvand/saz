"""Agentic plans must stay within the workflow's declared tool allowlist.

A registered-but-undeclared tool must be blocked deterministically (before
execution and independent of the LLM verifier). A declared tool passes.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.orm import Session

from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import ExecutionPlan, PlanStep
from saz.db.models import Event, Flow, Run
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor, derive_declared_tools
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
WEBHOOK_SPEC = {
    "name": "webhook_emit",
    "description": "fake",
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string"}, "payload": {"type": "object"}},
        "required": ["url", "payload"],
    },
}


def test_derive_declared_tools_unit():
    spec = {
        "allowed_tools": ["http_request"],
        "steps": [
            {"id": "a", "type": "ai.extract"},
            {"id": "b", "type": "tool.call", "tool": "artifact.store"},
            {"id": "c", "type": "human.approval"},
        ],
    }
    assert derive_declared_tools(spec) == {"http_request", "ai.extract", "artifact.store"}


def _seed_agentic_flow(db_engine, allowed_tools):
    with Session(db_engine) as session:
        session.add_all(
            [
                Flow(
                    created_by_user_id=TEST_USER_ID,
                    id="flow_agz",
                    name="flow_agz",
                    definition={
                        "schema_version": 1,
                        "flow": {"name": "agz", "description": "agentic allowlist"},
                        "workflow": {
                            "planner_mode": "agentic",
                            "steps": [],
                            "allowed_tools": allowed_tools,
                        },
                        "policies": {"budget_usd": 5.0},
                    },
                ),
                Run(
                    created_by_user_id=TEST_USER_ID,
                    id="run_agz",
                    flow_id="flow_agz",
                    status="queued",
                    planner_mode="agentic",
                    payload={},
                ),
            ]
        )
        session.commit()


def _planner_returning(tool_name: str):
    planner = MagicMock()
    planner.plan = AsyncMock(
        return_value=ExecutionPlan(
            plan_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            steps=[
                PlanStep(
                    step_id="s1",
                    step_type="tool.call",
                    tool_name=tool_name,
                    input_template={"method": "GET", "url": "https://api.example.com/x"}
                    if tool_name == "http_request"
                    else {"url": "https://api.example.com/x", "payload": {}},
                    expected_output_schema={},
                    reasoning="probe",
                )
            ],
            estimated_cost_usd=0.0,
            estimated_time_seconds=0,
            reasoning="probe",
        )
    )
    return planner


def _registry():
    reg = ToolRegistry()
    http = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    wh = RecordingTool("webhook_emit", response={"ok": True}, spec=WEBHOOK_SPEC)
    reg.register_custom_tool("http_request", http.spec, http.execute)
    reg.register_custom_tool("webhook_emit", wh.spec, wh.execute)
    return reg, http, wh


def test_agentic_undeclared_tool_blocked(db_engine):
    _seed_agentic_flow(db_engine, allowed_tools=["http_request"])
    reg, http, wh = _registry()
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = WorkflowExecutor(
                uow=uow,
                tool_registry=reg,
                planner=_planner_returning("webhook_emit"),  # NOT allowed
                executor_agent=ExecutorAgent(),
                critic=FakeCritic(),  # type: ignore[arg-type]
                policy_engine=PolicyEngine(),
            )
            try:
                asyncio.run(executor.execute_run("run_agz"))
            except Exception:
                pass

    assert wh.call_count == 0, "undeclared tool must not execute"
    assert http.call_count == 0
    with Session(db_engine) as session:
        run = session.get(Run, "run_agz")
        assert run.status in ("failed", "error")
        types = [e.event_type for e in session.query(Event).filter(Event.run_id == "run_agz").all()]
        assert "policy.blocked" in types, types


def test_agentic_declared_tool_allowed(db_engine):
    _seed_agentic_flow(db_engine, allowed_tools=["http_request"])
    reg, http, wh = _registry()
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = WorkflowExecutor(
                uow=uow,
                tool_registry=reg,
                planner=_planner_returning("http_request"),  # allowed
                executor_agent=ExecutorAgent(),
                critic=FakeCritic(),  # type: ignore[arg-type]
                policy_engine=PolicyEngine(),
            )
            asyncio.run(executor.execute_run("run_agz"))

    assert http.call_count == 1, "declared tool should execute"
    with Session(db_engine) as session:
        run = session.get(Run, "run_agz")
        assert run.status == "completed"
