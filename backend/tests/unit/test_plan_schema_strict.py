"""ExecutionPlan / PlanStep must reject malformed planner output.

A hallucinating LLM planner can emit extra keys, omit a tool name, or invent a
step type. The schema must fail closed so the executor never runs a plan it
cannot interpret.
"""

import pytest
from pydantic import ValidationError

from saz.agents.schemas import ExecutionPlan, PlanStep

VALID_PLAN_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _tool_step(**overrides):
    base = dict(
        step_id="s1",
        step_type="tool.call",
        tool_name="http_request",
        reasoning="r",
    )
    base.update(overrides)
    return base


def test_valid_plan_step_passes():
    step = PlanStep(**_tool_step())
    assert step.tool_name == "http_request"


def test_extra_field_on_plan_step_rejected():
    with pytest.raises(ValidationError):
        PlanStep(**_tool_step(hallucinated="oops"))


def test_tool_call_without_tool_name_rejected():
    with pytest.raises(ValidationError):
        PlanStep(step_id="s1", step_type="tool.call", reasoning="r")


def test_unknown_step_type_rejected():
    with pytest.raises(ValidationError):
        PlanStep(step_id="s1", step_type="magic.do", reasoning="r")


def test_ai_and_artifact_prefixes_accepted():
    assert PlanStep(step_id="a", step_type="ai.extract", reasoning="r").tool_name is None
    assert PlanStep(step_id="b", step_type="artifact.store", reasoning="r").step_type == (
        "artifact.store"
    )


def test_control_steps_need_no_tool_name():
    for st in ("condition", "human.approval", "webhook.wait"):
        PlanStep(step_id="c", step_type=st, reasoning="r")


def test_valid_execution_plan_passes():
    plan = ExecutionPlan(
        plan_id=VALID_PLAN_ID,
        steps=[PlanStep(**_tool_step())],
        estimated_cost_usd=0.0,
        estimated_time_seconds=0,
        reasoning="ok",
    )
    assert len(plan.steps) == 1


def test_extra_field_on_execution_plan_rejected():
    with pytest.raises(ValidationError):
        ExecutionPlan(
            plan_id=VALID_PLAN_ID,
            steps=[],
            estimated_cost_usd=0.0,
            estimated_time_seconds=0,
            reasoning="ok",
            invented="nope",
        )
