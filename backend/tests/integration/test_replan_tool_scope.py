"""Regression: the replanner must only be shown the workflow's declared tools.

The initial agentic plan advertises only ``context['allowed_tools']`` so the
planner never proposes a tool the runtime would deny. The replan path passed
``self.tool_registry.get_tool_specs()`` (the FULL registry) instead, leaking
undeclared tools into the replan prompt and wasting a replan attempt on tools
the grounding gate would block anyway.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.orm import Session

from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import ExecutionPlan, PlanStep, Verdict
from saz.db.models import Flow, Run
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
    "inputSchema": {
        "type": "object",
        "properties": {"method": {"type": "string"}, "url": {"type": "string"}},
        "required": ["method", "url"],
    },
}
EMIT_SPEC = {
    "name": "webhook_emit",
    "description": "fake undeclared tool",
    "inputSchema": {"type": "object", "properties": {}, "required": []},
}


def _seed_flow(db_engine):
    with Session(db_engine) as session:
        session.add_all(
            [
                Flow(
                    created_by_user_id=TEST_USER_ID,
                    id="flow_replan_scope",
                    name="flow_replan_scope",
                    definition={
                        "schema_version": 1,
                        "flow": {"name": "rs", "description": "replan scope"},
                        "workflow": {
                            "planner_mode": "agentic",
                            "steps": [],
                            "allowed_tools": ["http_request"],
                        },
                        "policies": {"budget_usd": 5.0, "max_replan_attempts": 2},
                    },
                ),
                Run(
                    created_by_user_id=TEST_USER_ID,
                    id="run_replan_scope",
                    flow_id="flow_replan_scope",
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


def test_replanner_only_sees_declared_tools(db_engine):
    _seed_flow(db_engine)
    reg = ToolRegistry()
    http = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    emit = RecordingTool("webhook_emit", response={"ok": True}, spec=EMIT_SPEC)
    reg.register_custom_tool("http_request", http.spec, http.execute)
    reg.register_custom_tool("webhook_emit", emit.spec, emit.execute)

    planner = _http_plan()
    # Verifier: REPLAN once (drives the replan path), then PASS so the revised
    # step executes and the run finishes.
    critic = FakeCritic(verify_verdicts=[Verdict.REPLAN, Verdict.PASS])

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        executor = WorkflowExecutor(
            uow=uow,
            tool_registry=reg,
            planner=planner,
            executor_agent=ExecutorAgent(),
            critic=critic,  # type: ignore[arg-type]
            policy_engine=PolicyEngine(),
        )
        asyncio.run(executor.execute_run("run_replan_scope"))

    # planner.plan called at least twice: initial plan + replan.
    assert planner.plan.call_count >= 2, planner.plan.call_count
    replan_specs = planner.plan.call_args_list[1].kwargs["tool_registry"]
    names = {s.get("name") for s in replan_specs}
    assert names == {"http_request"}, (
        f"replanner was shown undeclared tools: {names}; only declared tools "
        "(http_request) should be advertised"
    )
