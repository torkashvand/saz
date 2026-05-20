"""Acceptance: replan loop exhaustion fails the run without executing the tool.

When the pre-execution verifier returns REPLAN repeatedly, the executor
re-grounds and re-verifies up to ``max_replan_attempts``. Past that cap
it must stop, never execute the tool, and surface a structured failure.
"""

import asyncio

import pytest
from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import Verdict
from saz.db.models import Flow, Run, Step
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


@pytest.fixture
def one_step_flow_low_replan(db_engine):
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_acc_replan_1",
            name="acc_replan",
            definition={
                "schema_version": 1,
                "flow": {"name": "acc_replan", "description": "replan exhaustion"},
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "send",
                            "type": "tool.call",
                            "description": "Outbound call",
                            "tool": "http_request",
                            "params": {"method": "POST", "url": "https://api.example.com/x"},
                        }
                    ],
                },
                "policies": {"budget_usd": 1.0, "max_replan_attempts": 1},
            },
        )
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_acc_replan_1",
            flow_id="flow_acc_replan_1",
            status="queued",
            planner_mode="deterministic",
            payload={},
        )
        session.add_all([flow, run])
        session.commit()
    return "run_acc_replan_1"


def test_replan_exhaustion_blocks_execution_and_fails_run(one_step_flow_low_replan, db_engine):
    run_id = one_step_flow_low_replan

    fake_http = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    registry = ToolRegistry()
    registry.register_custom_tool("http_request", fake_http.spec, fake_http.execute)

    critic = FakeCritic(default_verify=Verdict.REPLAN)

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = WorkflowExecutor(
                uow=uow,
                tool_registry=registry,
                planner=DeterministicPlanner(),
                executor_agent=ExecutorAgent(),
                critic=critic,  # type: ignore[arg-type]
                policy_engine=PolicyEngine(max_replan_attempts=1),
            )
            try:
                asyncio.run(executor.execute_run(run_id))
            except Exception:
                pass

    assert fake_http.call_count == 0, (
        f"http_request was called {fake_http.call_count} times despite "
        "every verify_proposal returning REPLAN. Replan exhaustion must "
        "fail-closed without executing the tool."
    )

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.status == "failed", (
            f"run must end in a terminal failure state after replan "
            f"exhaustion; got {run.status!r}"
        )
        steps = session.query(Step).filter(Step.run_id == run_id).all()
        actual_status = steps[0].status if steps else None
        assert steps and steps[0].status == "failed", (
            "the step must be marked failed once replans are exhausted; "
            f"got status={actual_status!r}"
        )
