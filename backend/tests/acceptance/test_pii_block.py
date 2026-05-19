"""Acceptance: PII on a non-allow-listed path blocks an outbound tool call.

The PolicyEngine's outbound-tool path is the trust boundary: a call leaving
Saz's perimeter cannot carry PII on paths the operator hasn't explicitly
opted in. When the check fails, the tool must not execute and the run
must terminate with a structured failure.
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
            "body": {"type": "object"},
        },
        "required": ["method", "url"],
    },
}


@pytest.fixture
def pii_emitting_flow(db_engine):
    with Session(db_engine) as session:
        flow = Flow(
            id="flow_acc_pii",
            name="acc_pii",
            definition={
                "schema_version": 1,
                "flow": {"name": "acc_pii", "description": "PII outbound block"},
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "leak",
                            "type": "tool.call",
                            "description": "Send a request containing an unmasked email",
                            "tool": "http_request",
                            "params": {
                                "method": "POST",
                                "url": "https://api.example.com/contact",
                                "body": {
                                    "comment": "Reach me at user@example.com",
                                },
                            },
                        }
                    ],
                },
                "policies": {
                    "budget_usd": 1.0,
                    "pii": {"allow": False},
                },
            },
        )
        run = Run(
            id="run_acc_pii_1",
            flow_id="flow_acc_pii",
            status="queued",
            planner_mode="deterministic",
            payload={},
        )
        session.add_all([flow, run])
        session.commit()
    return "run_acc_pii_1"


def test_pii_on_disallowed_path_blocks_outbound_tool(pii_emitting_flow, db_engine):
    run_id = pii_emitting_flow

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
                policy_engine=PolicyEngine(enforce_pii_redaction=True),
            )
            try:
                asyncio.run(executor.execute_run(run_id))
            except Exception:
                pass

    assert fake_http.call_count == 0, (
        f"http_request was called {fake_http.call_count} times with PII in "
        "the body — outbound PII block is broken."
    )

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        steps = session.query(Step).filter(Step.run_id == run_id).all()
        assert run.status in (
            "failed",
            "error",
        ), f"run must fail when policy blocks the outbound call; got {run.status!r}"
        assert steps and steps[0].status == "failed", (
            f"step must be marked failed on policy block; got "
            f"status={(steps[0].status if steps else None)!r}"
        )
