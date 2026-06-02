"""DSL policy fields declared in YAML must actually affect runtime.

The runtime executes the raw validated DSL and PolicyEngine.initialize_from_dsl
reads the policies block from it. This proves a policy declared only in YAML
(max_steps) reaches the BudgetTracker and changes execution.
"""

import asyncio

from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.db.models import Event, Flow as FlowModel, Run, Step
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.globals import create_policy_engine, initialize_globals
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


def test_dsl_max_steps_limits_runtime(db_engine):
    initialize_globals()
    step = {
        "id": "x",
        "type": "tool.call",
        "description": "call",
        "tool": "http_request",
        "params": {"method": "GET", "url": "https://api.example.com/x"},
    }
    definition = {
        "schema_version": 1,
        "flow": {"name": "ms", "description": "max steps"},
        "workflow": {
            "planner_mode": "deterministic",
            "steps": [{**step, "id": "s1"}, {**step, "id": "s2"}],
        },
        # max_steps declared ONLY in YAML policies — must reach the runtime.
        "policies": {"budget_usd": 5.0, "max_steps": 1},
    }
    with Session(db_engine) as session:
        session.add_all(
            [
                FlowModel(
                    created_by_user_id=TEST_USER_ID,
                    id="flow_ms",
                    name="flow_ms",
                    definition=definition,
                ),
                Run(
                    created_by_user_id=TEST_USER_ID,
                    id="run_ms",
                    flow_id="flow_ms",
                    status="queued",
                    planner_mode="deterministic",
                    payload={},
                ),
            ]
        )
        session.commit()

    tool = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
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
                policy_engine=create_policy_engine(),
            )
            try:
                asyncio.run(executor.execute_run("run_ms"))
            except Exception:
                pass

    # Only the first step ran; the second was blocked by the DSL max_steps cap.
    assert tool.call_count == 1, f"max_steps=1 not enforced (calls={tool.call_count})"
    with Session(db_engine) as session:
        run = session.get(Run, "run_ms")
        assert run.status in ("failed", "error")
        types = [e.event_type for e in session.query(Event).filter(Event.run_id == "run_ms").all()]
        assert "policy.budget.exhausted" in types, types
        completed_steps = (
            session.query(Step).filter(Step.run_id == "run_ms", Step.status == "completed").count()
        )
        assert completed_steps == 1
