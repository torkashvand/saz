"""Budget limits are per run, not per execution segment.

The policy engine (and its in-memory BudgetTracker) is created fresh for
every execution segment — initial run, resume after suspension, retry. A
budget_usd cap must account for spend persisted on prior step rows, or a
run with a mid-flow approval gate gets a full fresh budget after every
resume and can legally spend N x its cap.
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


def _seed(session: Session, run_id: str, prior_cost_usd: float, budget_usd: float) -> None:
    """A re-queued run (post-resume/retry) whose first step already completed
    in a previous segment, with its spend persisted on the step row."""
    session.add(
        Flow(
            created_by_user_id=TEST_USER_ID,
            id=f"flow_{run_id}",
            name=f"flow_{run_id}",
            definition={
                "schema_version": 1,
                "flow": {"name": run_id, "description": "budget across segments"},
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "done_step",
                            "type": "tool.call",
                            "description": "already completed in a prior segment",
                            "tool": "http_request",
                            "params": {"method": "GET", "url": "https://api.example/a"},
                        },
                        {
                            "id": "next_step",
                            "type": "tool.call",
                            "description": "should be budget-gated",
                            "tool": "http_request",
                            "params": {"method": "GET", "url": "https://api.example/b"},
                        },
                    ],
                },
                "policies": {"budget_usd": budget_usd},
            },
        )
    )
    session.add(
        Run(
            created_by_user_id=TEST_USER_ID,
            id=run_id,
            flow_id=f"flow_{run_id}",
            status="queued",
            planner_mode="deterministic",
            payload={},
        )
    )
    session.commit()
    session.add(
        Step(
            id=f"step_{run_id}_done",
            run_id=run_id,
            number=0,
            name="done_step",
            step_type="tool.call",
            status="completed",
            attempt=0,
            output={"ok": True},
            tokens=1000,
            cost_usd=prior_cost_usd,
        )
    )
    session.commit()


def _run(db_engine, run_id: str, tool: RecordingTool) -> None:
    registry = ToolRegistry()
    registry.register_custom_tool("http_request", tool.spec, tool.execute)
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


def test_budget_spent_in_prior_segment_blocks_next_segment(db_engine):
    """Prior-segment spend above the cap must fail the run before the next
    tool executes — no fresh budget per segment."""
    run_id = "run_budget_seg_over"
    with Session(db_engine) as session:
        _seed(session, run_id, prior_cost_usd=6.0, budget_usd=5.0)

    tool = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    _run(db_engine, run_id, tool)

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.error is not None
        assert run.error.get("type") == "BudgetExceededError"

    # The forbidden side effect: the second tool call never happened.
    assert tool.call_count == 0


def test_budget_within_cap_still_resumes_normally(db_engine):
    """Control: prior spend under the cap must not block the next segment."""
    run_id = "run_budget_seg_ok"
    with Session(db_engine) as session:
        _seed(session, run_id, prior_cost_usd=1.0, budget_usd=5.0)

    tool = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    _run(db_engine, run_id, tool)

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.status == "completed"

    # Only the not-yet-completed step executed; the restored one was skipped.
    assert tool.call_count == 1
