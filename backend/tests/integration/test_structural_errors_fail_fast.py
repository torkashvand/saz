"""Structural workflow errors must fail fast (no retry/backoff).

Tool-not-found, missing required arguments, and unresolved templates are
permanent — retrying only wastes time and budget. They must mark the step
failed on the first attempt with a non-retryable, structured error.
"""

import asyncio

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
    "description": "fake",
    "input_schema": {
        "type": "object",
        "properties": {"method": {"type": "string"}, "url": {"type": "string"}},
        "required": ["method", "url"],
    },
}


def _seed(session, run_id, step):
    session.add_all(
        [
            Flow(
                created_by_user_id=TEST_USER_ID,
                id=f"flow_{run_id}",
                name=f"flow_{run_id}",
                definition={
                    "schema_version": 1,
                    "flow": {"name": run_id, "description": "structural"},
                    "workflow": {
                        "planner_mode": "deterministic",
                        # retry.attempts high to prove we do NOT retry structurally.
                        "steps": [{**step, "retry": {"attempts": 5}}],
                    },
                    "policies": {"budget_usd": 5.0},
                },
            ),
            Run(
                created_by_user_id=TEST_USER_ID,
                id=run_id,
                flow_id=f"flow_{run_id}",
                status="queued",
                planner_mode="deterministic",
                payload={},
            ),
        ]
    )
    session.commit()


def _run(db_engine, run_id, registry):
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = WorkflowExecutor(
                uow=uow,
                tool_registry=registry,
                planner=DeterministicPlanner(),
                executor_agent=ExecutorAgent(),
                critic=FakeCritic(),  # type: ignore[arg-type]
                policy_engine=PolicyEngine(),
            )
            try:
                asyncio.run(executor.execute_run(run_id))
            except Exception:
                pass


def test_tool_not_found_fails_fast(db_engine):
    with Session(db_engine) as session:
        _seed(
            session,
            "run_struct_tnf",
            {
                "id": "ghost",
                "type": "tool.call",
                "description": "call a missing tool",
                "tool": "does_not_exist",
                "params": {"x": 1},
            },
        )
    # Registry has http_request only — the referenced tool is absent.
    registry = ToolRegistry()
    tool = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    registry.register_custom_tool("http_request", tool.spec, tool.execute)

    _run(db_engine, "run_struct_tnf", registry)

    with Session(db_engine) as session:
        run = session.get(Run, "run_struct_tnf")
        assert run.status in ("failed", "error")
        assert run.error.get("type") == "ToolNotFoundError"
        assert run.error.get("retryable") is False
        step = session.query(Step).filter(Step.run_id == "run_struct_tnf").first()
        assert step is not None and step.status == "failed"
        # Fail-fast: never retried despite retry.attempts=5.
        assert (step.retry_count or 0) == 0
        assert step.error.get("type") == "ToolNotFoundError"


def test_missing_required_args_fails_fast(db_engine):
    with Session(db_engine) as session:
        _seed(
            session,
            "run_struct_args",
            {
                "id": "bad",
                "type": "tool.call",
                "description": "missing url",
                "tool": "http_request",
                "params": {"method": "GET"},  # 'url' required but absent
            },
        )
    registry = ToolRegistry()
    tool = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    registry.register_custom_tool("http_request", tool.spec, tool.execute)

    _run(db_engine, "run_struct_args", registry)

    with Session(db_engine) as session:
        run = session.get(Run, "run_struct_args")
        assert run.status in ("failed", "error")
        assert run.error.get("type") == "InvalidToolArgumentsError"
        step = session.query(Step).filter(Step.run_id == "run_struct_args").first()
        assert step is not None and step.status == "failed"
        assert (step.retry_count or 0) == 0
        assert tool.call_count == 0
