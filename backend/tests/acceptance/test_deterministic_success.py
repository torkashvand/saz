"""Acceptance: a deterministic workflow runs end-to-end against real components.

Unlike the existing integration tests that mock most collaborators with
MagicMock, this test wires up the REAL WorkflowExecutor, REAL
DeterministicPlanner, REAL ExecutorAgent, and REAL ToolRegistry. Only
the critic and the tools themselves are fakes — and those fakes
satisfy the production interfaces, not MagicMock surfaces.

What this proves:
  - A registered flow's run can be executed via execute_run().
  - DeterministicPlanner → grounding → tool execution → post-execution
    critique completes without raising for a happy path.
  - Each declared step appears as a completed Step row.
  - Step.input is grounded with the resolved template values.
  - Step.output reflects the tool result.
  - Run reaches status='completed' with started_at and duration_ms set.
"""

import asyncio

import pytest
from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
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
        "properties": {
            "method": {"type": "string"},
            "url": {"type": "string"},
        },
        "required": ["method", "url"],
    },
}


@pytest.fixture
def deterministic_flow(db_engine):
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_acc_det_1",
            name="acc_det_happy",
            definition={
                "schema_version": 1,
                "flow": {"name": "acc_det_happy", "description": "happy path acceptance"},
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "fetch",
                            "type": "tool.call",
                            "description": "Fetch user record",
                            "tool": "http_request",
                            "params": {
                                "method": "GET",
                                "url": "https://api.example.com/users/{{ $form.user_id }}",
                            },
                        },
                        {
                            "id": "notify",
                            "type": "tool.call",
                            "description": "POST notification with the prior step's result",
                            "tool": "http_request",
                            "params": {
                                "method": "POST",
                                "url": "https://api.example.com/notify",
                            },
                        },
                    ],
                },
                "policies": {"budget_usd": 1.0},
            },
        )
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_acc_det_1",
            flow_id="flow_acc_det_1",
            status="queued",
            planner_mode="deterministic",
            payload={"user_id": "u42"},
        )
        session.add_all([flow, run])
        session.commit()
    return "run_acc_det_1"


def test_deterministic_workflow_runs_to_completion(deterministic_flow, db_engine):
    run_id = deterministic_flow

    fake_http = RecordingTool(
        name="http_request",
        response={"ok": True, "body": {"id": "u42"}, "status_code": 200},
        spec=HTTP_SPEC,
    )

    registry = ToolRegistry()
    registry.register_custom_tool("http_request", fake_http.spec, fake_http.execute)

    critic = FakeCritic()

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
            asyncio.run(executor.execute_run(run_id))

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.status == "completed", f"run.status={run.status!r}, run.error={run.error!r}"
        assert run.started_at is not None, "started_at must be set by mark_running"
        assert (
            run.duration_ms is not None and run.duration_ms >= 0
        ), "duration_ms must be persisted, not left NULL"

        steps = session.query(Step).filter(Step.run_id == run_id).order_by(Step.number).all()
        statuses = [(s.name, s.status) for s in steps]
        assert statuses == [("fetch", "completed"), ("notify", "completed")], statuses

        fetch_step = next(s for s in steps if s.name == "fetch")
        assert fetch_step.input is not None
        assert "u42" in str(
            fetch_step.input
        ), f"Template should resolve $form.user_id, got input={fetch_step.input!r}"
        assert fetch_step.output is not None
        assert fetch_step.output.get("status_code") == 200

    assert (
        fake_http.call_count == 2
    ), f"http_request should have been called once per step, got {fake_http.call_count}"
    assert len(critic.verify_calls) == 2, "pre-execution verifier should fire for each tool step"
    assert len(critic.critique_calls) == 2, "post-execution critic should fire for each tool step"
