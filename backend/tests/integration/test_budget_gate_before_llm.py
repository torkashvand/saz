"""Regression: budget must gate the verifier/critique LLM calls.

The pre-execution policy check gates the tool call, but the post-execution
critique is a separate LLM call. Tool execution between them records cost, so a
step could overshoot the cap by a full critique spend. Budget must be
re-checked immediately before the critique LLM call.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.orm import Session

from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import ExecutionPlan, PlanStep
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


def _seed_flow(db_engine):
    with Session(db_engine) as session:
        session.add_all(
            [
                Flow(
                    created_by_user_id=TEST_USER_ID,
                    id="flow_budget_gate",
                    name="flow_budget_gate",
                    definition={
                        "schema_version": 1,
                        "flow": {"name": "bg", "description": "budget gate"},
                        "workflow": {
                            "planner_mode": "agentic",
                            "steps": [],
                            "allowed_tools": ["http_request"],
                        },
                        "policies": {"budget_usd": 1.0},
                    },
                ),
                Run(
                    created_by_user_id=TEST_USER_ID,
                    id="run_budget_gate",
                    flow_id="flow_budget_gate",
                    status="queued",
                    planner_mode="agentic",
                    payload={},
                ),
            ]
        )
        session.commit()


def _http_plan():
    planner = MagicMock()
    planner.plan = AsyncMock(
        return_value=ExecutionPlan(
            plan_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            steps=[
                PlanStep(
                    step_id="s1",
                    step_type="tool.call",
                    tool_name="http_request",
                    input_template={"method": "GET", "url": "https://api.example.com/x"},
                    reasoning="probe",
                )
            ],
            estimated_cost_usd=0.0,
            estimated_time_seconds=0,
            reasoning="probe",
        )
    )
    return planner


def test_exhausted_budget_blocks_before_critique(db_engine):
    _seed_flow(db_engine)
    reg = ToolRegistry()
    # Tool execution reports a cost ($5) that blows the $1 budget; the critique
    # LLM call that follows must be blocked.
    http = RecordingTool(
        "http_request",
        response={"ok": True, "usage": {"tokens": 5000, "cost_usd": 5.0}},
        spec=HTTP_SPEC,
    )
    reg.register_custom_tool("http_request", http.spec, http.execute)
    critic = FakeCritic()

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        executor = WorkflowExecutor(
            uow=uow,
            tool_registry=reg,
            planner=_http_plan(),
            executor_agent=ExecutorAgent(),
            critic=critic,  # type: ignore[arg-type]
            policy_engine=PolicyEngine(),
        )
        asyncio.run(executor.execute_run("run_budget_gate"))

    # The tool ran (it reported the cost), but the critique LLM must NOT have
    # been called once the budget was spent.
    assert http.call_count == 1
    assert critic.critique_calls == [], "critique LLM ran despite an exhausted budget"

    with Session(db_engine) as session:
        run = session.get(Run, "run_budget_gate")
        assert run.status in ("failed", "error"), run.status
        types = [
            e.event_type
            for e in session.query(Event).filter(Event.run_id == "run_budget_gate").all()
        ]
        assert "policy.budget.exhausted" in types, types
