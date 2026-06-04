"""Acceptance: pre-execution verifier FAIL must block the tool before it runs.

The dual-agent safety model relies on `critic.verify_proposal()` running
*before* tool execution. If a FAIL verdict still results in the tool
being invoked, the safety claim is hollow. This test proves that no
recorded tool call ever happens on a FAIL verdict, and that the run is
left in a terminal failure state with the verifier's reasoning
attributable through step.error or step.policy_flags.
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
def one_step_flow(db_engine):
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_acc_block_1",
            name="acc_block",
            definition={
                "schema_version": 1,
                "flow": {"name": "acc_block", "description": "verifier blocking acceptance"},
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "ship_it",
                            "type": "tool.call",
                            "description": "Side-effectful call that must be blocked",
                            "tool": "http_request",
                            "params": {
                                "method": "POST",
                                "url": "https://api.example.com/launch",
                            },
                        },
                    ],
                },
                "policies": {"budget_usd": 1.0, "max_replan_attempts": 0},
            },
        )
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_acc_block_1",
            flow_id="flow_acc_block_1",
            status="queued",
            planner_mode="deterministic",
            payload={},
        )
        session.add_all([flow, run])
        session.commit()
    return "run_acc_block_1"


def test_verifier_fail_blocks_tool_execution(one_step_flow, db_engine):
    run_id = one_step_flow

    fake_http = RecordingTool(
        name="http_request",
        response={"ok": True, "status_code": 200},
        spec=HTTP_SPEC,
    )

    registry = ToolRegistry()
    registry.register_custom_tool("http_request", fake_http.spec, fake_http.execute)

    # default_verify=FAIL — the executor's outer retry can call
    # verify_proposal more than once per step, so a one-shot FAIL queue
    # silently flips to PASS on retry. We want every verify to fail.
    critic = FakeCritic(default_verify=Verdict.FAIL)

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = WorkflowExecutor(
                uow=uow,
                tool_registry=registry,
                planner=DeterministicPlanner(),
                executor_agent=ExecutorAgent(),
                critic=critic,  # type: ignore[arg-type]
                policy_engine=PolicyEngine(),
            )
            # execute_run captures internal failures and marks the run failed;
            # it should NOT propagate the critique exception as an unhandled
            # error to the caller — execute_run handles it and fails the run.
            asyncio.run(executor.execute_run(run_id))

    assert fake_http.call_count == 0, (
        f"http_request was called {fake_http.call_count} times despite the "
        "verifier returning FAIL. The pre-execution safety gate is broken."
    )

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.status == "failed", (
            f"run must end in a terminal failure state when the verifier "
            f"rejects the only step; got {run.status!r}"
        )

        steps = session.query(Step).filter(Step.run_id == run_id).all()
        assert steps, "step row should exist even on pre-execution failure"
        ship_step = steps[0]
        assert ship_step.status == "failed", (
            f"step ship_it must be marked failed when its proposal is rejected; "
            f"got {ship_step.status!r}"
        )

    assert len(critic.verify_calls) >= 1, "verify_proposal must have been called"
    assert len(critic.critique_calls) == 0, (
        "post-execution critique must not run if the pre-execution verifier "
        f"blocked the call. Got {len(critic.critique_calls)} critique calls."
    )
