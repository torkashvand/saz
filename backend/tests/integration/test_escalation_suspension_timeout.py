"""Regression: verifier ESCALATE suspensions must carry a timeout deadline.

A pre-execution verifier ``ESCALATE`` verdict raises ``EscalationRequired``,
which the executor catches and turns into a suspended run. Like every other
suspension path (human approval, webhook wait, the generic ESCALATE error
handler) it must write ``error.timeout_at`` so the SuspensionSweeper can reap
it. Without it the run is suspended forever — unbounded suspended state.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.orm import Session

from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import ExecutionPlan, PlanStep, Verdict
from saz.db.models import Flow, Run
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.engine.suspension_sweeper import SuspensionSweeper
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


def _seed_flow(db_engine):
    with Session(db_engine) as session:
        session.add_all(
            [
                Flow(
                    created_by_user_id=TEST_USER_ID,
                    id="flow_esc",
                    name="flow_esc",
                    definition={
                        "schema_version": 1,
                        "flow": {"name": "esc", "description": "escalate"},
                        "workflow": {
                            "planner_mode": "agentic",
                            "steps": [],
                            "allowed_tools": ["http_request"],
                        },
                        "policies": {"budget_usd": 5.0},
                    },
                ),
                Run(
                    created_by_user_id=TEST_USER_ID,
                    id="run_esc",
                    flow_id="flow_esc",
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


def test_verifier_escalation_suspension_carries_timeout(db_engine):
    _seed_flow(db_engine)
    reg = ToolRegistry()
    http = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    reg.register_custom_tool("http_request", http.spec, http.execute)

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        executor = WorkflowExecutor(
            uow=uow,
            tool_registry=reg,
            planner=_http_plan(),
            executor_agent=ExecutorAgent(),
            critic=FakeCritic(default_verify=Verdict.ESCALATE),  # type: ignore[arg-type]
            policy_engine=PolicyEngine(),
        )
        asyncio.run(executor.execute_run("run_esc"))

    # The escalated tool must never have executed.
    assert http.call_count == 0

    with Session(db_engine) as session:
        run = session.get(Run, "run_esc")
        assert run.status == "suspended"
        assert run.error and run.error.get("type") == "EscalationRequired"
        # The bug: this path never attached timeout metadata.
        assert run.error.get(
            "timeout_at"
        ), "escalation suspension must carry timeout_at so the sweeper can reap it"

        # Rewind the deadline into the past and let the sweeper reap it.
        error = dict(run.error)
        error["timeout_at"] = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        run.error = error
        session.commit()

    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        interval_seconds=60,
        batch_limit=10,
        engine=db_engine,
    )
    swept = sweeper.sweep_once()
    assert swept >= 1

    with Session(db_engine) as session:
        run = session.get(Run, "run_esc")
        assert run.status == "failed"
        assert run.error and run.error.get("type") == "SuspensionTimeout"
