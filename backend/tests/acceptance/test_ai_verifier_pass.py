"""Acceptance: an ai.* step grounded against a fake LLM completes end-to-end.

Wires together:
  - Real WorkflowExecutor + DeterministicPlanner + ExecutorAgent
  - Real PolicyEngine
  - Real ToolRegistry with AI ops registered against a fake LLM port
  - Fake critic returning PASS for both verify_proposal and critique

What this proves end-to-end:
  - The deterministic planner's AI-step grounding (with `expected_schema`)
    reaches the AI operations runner.
  - The AI op produces a structured output matching the declared `expect`.
  - The post-execution critique runs and approves.
  - The step lands as completed with a populated `output`.
"""

import asyncio
import json

import pytest
from sqlalchemy.orm import Session

from saz.agents.ai_ops import AIOperationsRunner
from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.db.models import Flow, Run, Step
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.tools.registry import ToolRegistry
from tests.conftest import TEST_USER_ID, MockLLMPort
from tests.fakes.critic import FakeCritic


@pytest.fixture
def ai_step_flow(db_engine):
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_acc_ai_pass",
            name="acc_ai_pass",
            definition={
                "schema_version": 1,
                "flow": {"name": "acc_ai_pass", "description": "AI step happy path"},
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "extract",
                            "type": "ai.extract",
                            "instruction": "Extract the order id and product from the message",
                            "expect": {
                                "properties": {
                                    "order_id": {"type": "string"},
                                    "product": {"type": "string"},
                                },
                                "required": ["order_id", "product"],
                            },
                        }
                    ],
                },
                "policies": {"budget_usd": 1.0},
            },
        )
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_acc_ai_pass_1",
            flow_id="flow_acc_ai_pass",
            status="queued",
            planner_mode="deterministic",
            payload={"text": "Order ORD-42 for widget needs review"},
        )
        session.add_all([flow, run])
        session.commit()
    return "run_acc_ai_pass_1"


def test_ai_extract_step_completes_with_structured_output(ai_step_flow, db_engine):
    run_id = ai_step_flow

    # Fake LLM returns a JSON object matching the declared `expect`. Avoid
    # email/PII tokens — the PolicyEngine redacts those in stored output,
    # which would muddy the assertion (we're testing AI op wiring here, not
    # PII handling).
    fake_llm = MockLLMPort(responses=[json.dumps({"order_id": "ORD-42", "product": "widget"})])
    ai_runner = AIOperationsRunner(llm_port=fake_llm)

    registry = ToolRegistry()
    registry.register_ai_ops(ai_runner)

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
        steps = session.query(Step).filter(Step.run_id == run_id).all()
        assert run.status == "completed", f"run.status={run.status!r}, error={run.error!r}"
        assert steps and steps[0].status == "completed"
        # The AI-op envelope ({"output": {...}, "usage": ..., "metadata": ...})
        # is unwrapped to its fields as the resolvable step output, so a
        # downstream $step('id').field reference reaches them directly.
        inner = steps[0].output or {}
        assert (
            inner.get("order_id") == "ORD-42"
        ), f"AI step output should include order_id=ORD-42; got {steps[0].output!r}"
        assert inner.get("product") == "widget"

    assert fake_llm.call_count >= 1, "ai.extract must have called the LLM"
    assert len(critic.verify_calls) == 1
    assert len(critic.critique_calls) == 1
