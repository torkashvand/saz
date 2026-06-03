"""An AI-op step's fields must be addressable by downstream `$step('id').field`.

Regression: AI-op tools return ``{"output": <fields>, "usage": ..., "metadata":
...}``. The templating layer resolves ``$step('id').field`` against the stored
step output directly, so without unwrapping the envelope every reference to an
AI field resolves to empty — which made the deterministic verifier flag "empty
data" and fail. This drives the real WorkflowExecutor with a fake AI tool that
returns the real envelope shape and asserts the field flows into the next step.
"""

import asyncio

from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.db.models import Flow, Run, Step
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor, _unwrap_ai_output
from saz.policies.policy_engine import PolicyEngine
from saz.tools.registry import ToolRegistry
from tests.conftest import TEST_USER_ID
from tests.fakes.critic import FakeCritic
from tests.fakes.tools import RecordingTool

AI_ENVELOPE = {
    "output": {"category": "billing", "priority": "high"},
    "usage": {"tokens": 5, "cost_usd": 0.0},
    "metadata": {"op": "ai.extract", "model": "fake"},
}

AI_SPEC = {
    "name": "ai.extract",
    "description": "fake model tool",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}
NOTIFY_SPEC = {
    "name": "notify",
    "description": "fake",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


def test_unwrap_ai_output_helper():
    # Structured AI-op envelope is unwrapped to its fields.
    assert _unwrap_ai_output("ai.extract", AI_ENVELOPE) == {
        "category": "billing",
        "priority": "high",
    }
    # Non-AI tools and flat dicts pass through unchanged.
    assert _unwrap_ai_output("http_request", {"status_code": 200}) == {"status_code": 200}
    assert _unwrap_ai_output("ai.extract", {"category": "x"}) == {"category": "x"}
    # Text-output ops keep the envelope (a bare string would break the dict
    # contract for Step.output / the API); content stays under `.output`.
    text_envelope = {"output": "a generated sentence", "usage": {"tokens": 3}, "metadata": {}}
    assert _unwrap_ai_output("ai.generate", text_envelope) == text_envelope


def test_ai_field_flows_into_downstream_step(db_engine):
    with Session(db_engine) as session:
        session.add(
            Flow(
                created_by_user_id=TEST_USER_ID,
                id="flow_chain",
                name="flow_chain",
                definition={
                    "schema_version": 1,
                    "flow": {"name": "chain", "description": "ai chaining"},
                    "workflow": {
                        "planner_mode": "deterministic",
                        "steps": [
                            {
                                "id": "classify",
                                "type": "ai.extract",
                                "instruction": "classify",
                                "params": {"data": {"text": "{{ $form.msg }}"}},
                            },
                            {
                                "id": "route",
                                "type": "tool.call",
                                "tool": "notify",
                                "description": "route using the classification",
                                "params": {
                                    "category": "{{ $step('classify').category }}",
                                    "priority": "{{ $step('classify').priority }}",
                                },
                            },
                        ],
                    },
                },
            )
        )
        session.add(
            Run(
                created_by_user_id=TEST_USER_ID,
                id="run_chain",
                flow_id="flow_chain",
                status="queued",
                planner_mode="deterministic",
                payload={"msg": "I was double charged on my invoice"},
            )
        )
        session.commit()

    reg = ToolRegistry()
    ai_tool = RecordingTool("ai.extract", response=dict(AI_ENVELOPE), spec=AI_SPEC)
    notify = RecordingTool("notify", response={"ok": True}, spec=NOTIFY_SPEC)
    reg.register_custom_tool("ai.extract", ai_tool.spec, ai_tool.execute)
    reg.register_custom_tool("notify", notify.spec, notify.execute)

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        executor = WorkflowExecutor(
            uow=uow,
            tool_registry=reg,
            planner=DeterministicPlanner(),
            executor_agent=ExecutorAgent(),
            critic=FakeCritic(),  # type: ignore[arg-type]
            policy_engine=PolicyEngine(),
        )
        asyncio.run(executor.execute_run("run_chain"))

    # The downstream tool must have received the AI fields, not empty strings.
    assert notify.call_count == 1, "downstream step should have executed"
    args = notify.calls[0]
    assert args.get("category") == "billing", args
    assert args.get("priority") == "high", args

    with Session(db_engine) as session:
        run = session.get(Run, "run_chain")
        assert run.status == "completed", run.error
        # The persisted AI step output is the unwrapped fields, not the envelope.
        classify = (
            session.query(Step).filter(Step.run_id == "run_chain", Step.name == "classify").one()
        )
        assert classify.output == {"category": "billing", "priority": "high"}
