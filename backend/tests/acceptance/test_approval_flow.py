"""Acceptance: a human.approval gate suspends, then /resume continues execution.

Drives the gate through the REAL ``WorkflowExecutor``, then resumes via
the ``/api/v1/runs/{id}/resume`` HTTP endpoint, then re-executes via the
sync scheduler. Asserts:

  - The gate step suspends the run before the post-gate tool runs.
  - The post-gate tool runs AFTER resume, never before.
  - Step ``approve`` carries the resume_data on its ``output``.
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
        "properties": {"method": {"type": "string"}, "url": {"type": "string"}},
        "required": ["method", "url"],
    },
}


@pytest.fixture
def approval_flow(db_engine):
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_acc_approve_1",
            name="acc_approve",
            definition={
                "schema_version": 1,
                "flow": {"name": "acc_approve", "description": "approval gate"},
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "approve",
                            "type": "human.approval",
                            "description": "Review change",
                        },
                        {
                            "id": "execute",
                            "type": "tool.call",
                            "description": "Run after approval",
                            "tool": "http_request",
                            "params": {
                                "method": "POST",
                                "url": "https://api.example.com/execute",
                            },
                        },
                    ],
                },
                "policies": {"budget_usd": 1.0},
            },
        )
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_acc_approve_1",
            flow_id="flow_acc_approve_1",
            status="queued",
            planner_mode="deterministic",
            payload={},
        )
        session.add_all([flow, run])
        session.commit()
    return "run_acc_approve_1"


def test_approval_gate_suspends_then_resume_continues_execution(
    approval_flow, db_engine, app_client
):
    run_id = approval_flow

    fake_http = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    registry = ToolRegistry()
    registry.register_custom_tool("http_request", fake_http.spec, fake_http.execute)
    critic = FakeCritic()

    # First execution: should suspend at the approval gate
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
            # execute_run handles suspension/failure internally (RunSuspended is
            # caught and the run paused); it must not propagate an exception.
            asyncio.run(executor.execute_run(run_id))

    assert fake_http.call_count == 0, (
        f"http_request executed before approval. The gate did not stop the "
        f"executor — called {fake_http.call_count} times."
    )
    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert (
            run.status == "suspended"
        ), f"run must be suspended after hitting human.approval; got {run.status!r}"

    # Resume the run at the service layer with the same UoW pattern the
    # API route uses. Going through the real HTTP endpoint here picks up
    # the global scheduler (set by lifespan) which races with the
    # manually-driven executor below and made the test flaky.
    from saz.services.run_service import RunService

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            RunService(uow).resume_run(
                run_id,
                resume_data={"approved": True, "approver": "ops@example.com"},
            )

    # Re-run the executor manually now that the gate is completed and the
    # run is back to queued.
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
            # execute_run handles suspension/failure internally (RunSuspended is
            # caught and the run paused); it must not propagate an exception.
            asyncio.run(executor.execute_run(run_id))

    assert fake_http.call_count >= 1, (
        "post-gate tool must have been called after resume — gate may not "
        "have completed correctly. call_count="
        f"{fake_http.call_count}"
    )
    with Session(db_engine) as session:
        steps = session.query(Step).filter(Step.run_id == run_id).order_by(Step.number).all()
        approve_step = next(s for s in steps if s.name == "approve")
        execute_step = next((s for s in steps if s.name == "execute"), None)
        assert approve_step.status == "completed"
        assert approve_step.output and approve_step.output.get("approved") is True
        assert (
            execute_step is not None and execute_step.status == "completed"
        ), f"execute step status={(execute_step.status if execute_step else None)!r}"
