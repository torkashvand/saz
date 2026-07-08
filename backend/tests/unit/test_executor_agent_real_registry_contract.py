"""ExecutorAgent must validate required args against the REAL registry's tool specs.

Every tool spec carries its schema under ``input_schema``; the executor,
linter, and compiler all read that key. These tests pin the parity across
every registered tool AND that required-argument validation fires against
real (not hand-built) specs.
"""

import pytest

from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import ErrorHandling, PlanStep
from saz.tools.ansible_tool import AnsibleTool
from saz.tools.registry import _create_ai_tool_spec, create_default_registry


@pytest.fixture
def agent() -> ExecutorAgent:
    return ExecutorAgent()


def _make_step(tool_name: str, args: dict) -> PlanStep:
    return PlanStep(
        step_id="s1",
        step_type="tool.call",
        tool_name=tool_name,
        input_template=args,
        expected_output_schema={"type": "object"},
        error_handling=ErrorHandling.RETRY,
        max_retries=0,
        reasoning="test",
    )


def test_validates_required_fields_for_real_ai_tool_spec(agent):
    """Real AI tool specs use input_schema. Required-field validation should fire."""
    from saz.agents.ai_ops import AI_OPS

    # ai.extract requires `instruction`. Compose the real spec exactly as the
    # registry would expose it to the executor.
    ai_extract_spec = _create_ai_tool_spec("ai.extract", AI_OPS["ai.extract"])
    assert "input_schema" in ai_extract_spec
    assert "instruction" in ai_extract_spec["input_schema"]["required"]

    registry = {"ai.extract": ai_extract_spec}
    step = _make_step("ai.extract", args={"data": {"text": "hi"}})  # missing instruction

    with pytest.raises(ValueError, match="instruction"):
        agent.ground(step, registry, current_data={}, run_id="r1")


def test_validates_required_fields_for_real_ansible_tool_spec(agent):
    """AnsibleTool.spec uses input_schema. Required-field validation should fire."""
    ansible_spec = AnsibleTool().spec
    assert "input_schema" in ansible_spec
    required = set(ansible_spec["input_schema"]["required"])
    assert {"mode", "playbook", "inventory"} <= required

    registry = {"ansible_run": ansible_spec}
    # Missing inventory and playbook
    step = _make_step("ansible_run", args={"mode": "check"})

    with pytest.raises(ValueError, match="(playbook|inventory)"):
        agent.ground(step, registry, current_data={}, run_id="r1")


def test_validates_required_fields_for_http_tool_spec(agent):
    from saz.tools.http_tool import HttpTool

    http_spec = HttpTool().spec
    assert "input_schema" in http_spec
    required = set(http_spec["input_schema"]["required"])
    assert {"method", "url"} <= required

    registry = {"http_request": http_spec}
    step = _make_step("http_request", args={"method": "GET"})  # missing url

    with pytest.raises(ValueError, match="url"):
        agent.ground(step, registry, current_data={}, run_id="r1")


def test_every_registered_tool_spec_has_input_schema():
    """Parity pin: every spec carries `input_schema` — the executor, linter,
    and compiler all read that key, so a spec without it would silently skip
    required-argument validation everywhere."""
    registry = create_default_registry()
    for name in registry.list_tools():
        spec = registry.get_tool_spec(name)
        assert spec is not None
        assert isinstance(spec.get("input_schema"), dict), f"{name} missing input_schema"
