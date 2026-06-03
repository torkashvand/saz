"""Acceptance: a shipped example compiles AND executes end-to-end.

The existing example test only proves examples compile and register. This goes
one step further for a minimal shipped example: compile the raw YAML, build the
flow definition exactly as the compiler produces it, then drive a real
WorkflowExecutor (real DeterministicPlanner / ExecutorAgent / ToolRegistry,
fake critic + fake AI tool) so coverage reflects actual runtime semantics, not
just compile success. No real LLM or network is used.
"""

import asyncio
from pathlib import Path

from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.compiler.dsl import compile_dsl
from saz.db.models import Flow, Run, Step
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.tools.registry import ToolRegistry
from tests.conftest import TEST_USER_ID
from tests.fakes.critic import FakeCritic
from tests.fakes.tools import RecordingTool


def _strip_meta_section(yaml_content: str) -> str:
    """Drop the author-notes ``meta:`` block the strict DSL schema rejects."""
    if "meta:" not in yaml_content:
        return yaml_content
    lines = yaml_content.split("\n")
    out: list[str] = []
    in_meta = False
    for line in lines:
        if line.startswith("meta:"):
            in_meta = True
            continue
        if in_meta:
            # meta block continues while lines are indented or blank.
            if line and not line[0].isspace():
                in_meta = False
            else:
                continue
        out.append(line)
    return "\n".join(out)


_MINIMAL = (
    Path(__file__).parent.parent.parent / "saz" / "examples" / "unified" / "minimal_ai_step.yaml"
).resolve()

AI_EXTRACT_SPEC = {
    "name": "ai.extract",
    "description": "fake model tool",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


def test_minimal_example_compiles_and_executes(db_engine):
    compiled = compile_dsl(_strip_meta_section(_MINIMAL.read_text()))
    definition = {
        "schema_version": 1,
        "flow": {"name": compiled.flow_name, "description": compiled.flow_description},
        "workflow": compiled.workflow_spec,
        "policies": compiled.policies,
        "credentials": {"uses": compiled.credentials},
    }

    with Session(db_engine) as session:
        session.add(
            Flow(
                created_by_user_id=TEST_USER_ID,
                id="flow_ex",
                name=compiled.flow_name,
                definition=definition,
            )
        )
        session.add(
            Run(
                created_by_user_id=TEST_USER_ID,
                id="run_ex",
                flow_id="flow_ex",
                status="queued",
                planner_mode="deterministic",
                payload={"input_text": "Acme Corp met Alice in Berlin on 2026-01-01."},
            )
        )
        session.commit()

    reg = ToolRegistry()
    ai_tool = RecordingTool(
        "ai.extract",
        response={
            "people": ["Alice"],
            "organizations": ["Acme Corp"],
            "locations": ["Berlin"],
            "dates": ["2026-01-01"],
            "topics": [],
        },
        spec=AI_EXTRACT_SPEC,
    )
    reg.register_custom_tool("ai.extract", ai_tool.spec, ai_tool.execute)

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        executor = WorkflowExecutor(
            uow=uow,
            tool_registry=reg,
            planner=DeterministicPlanner(),
            executor_agent=ExecutorAgent(),
            critic=FakeCritic(),  # type: ignore[arg-type]
            policy_engine=PolicyEngine(),
        )
        asyncio.run(executor.execute_run("run_ex"))

    assert ai_tool.call_count == 1
    with Session(db_engine) as session:
        run = session.get(Run, "run_ex")
        assert run.status == "completed", run.error
        step = (
            session.query(Step)
            .filter(Step.run_id == "run_ex", Step.name == "extract_entities")
            .one()
        )
        assert step.status == "completed"
