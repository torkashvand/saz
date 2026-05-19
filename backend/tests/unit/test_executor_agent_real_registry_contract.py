"""ExecutorAgent must validate required args against the REAL registry's tool specs.

Bug being pinned: ExecutorAgent._validate_arguments() reads
`tool_spec.get("inputSchema", {})`. But the actual ToolRegistry produces
AI tool specs with `"input_schema"` (registry._create_ai_tool_spec, line 58)
and AnsibleTool.spec also uses `"input_schema"` (ansible_tool.py:66). Only
HttpTool / WebhookTool / ArtifactTool use the camelCase `"inputSchema"`.

The existing tests in tests/unit/test_agents.py pass because they hand-build
fake tool specs using `"inputSchema"`. Against real registry output the
required-argument check is silently bypassed.

These tests use the REAL registry's spec for AI tools and the real Ansible
spec. They fail today because `_validate_arguments()` reads the wrong key.
"""

import pytest

from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import ErrorHandling, PlanStep
from saz.tools.ansible_tool import AnsibleTool
from saz.tools.registry import _create_ai_tool_spec


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
    assert (
        "input_schema" in ai_extract_spec
    ), "sanity: registry produces input_schema, not inputSchema"
    assert "instruction" in ai_extract_spec["input_schema"]["required"]

    registry = {"ai.extract": ai_extract_spec}
    step = _make_step("ai.extract", args={"data": {"text": "hi"}})  # missing instruction

    with pytest.raises(ValueError, match="instruction"):
        agent.ground(step, registry, current_data={}, run_id="r1")


def test_validates_required_fields_for_real_ansible_tool_spec(agent):
    """AnsibleTool.spec uses input_schema. Required-field validation should fire."""
    ansible_spec = AnsibleTool().spec
    assert (
        "input_schema" in ansible_spec
    ), "sanity: AnsibleTool.spec uses input_schema, not inputSchema"
    required = set(ansible_spec["input_schema"]["required"])
    assert {"mode", "playbook", "inventory"} <= required

    registry = {"ansible_run": ansible_spec}
    # Missing inventory and playbook
    step = _make_step("ansible_run", args={"mode": "check"})

    with pytest.raises(ValueError, match="(playbook|inventory)"):
        agent.ground(step, registry, current_data={}, run_id="r1")


def test_still_validates_required_fields_for_inputSchema_specs(agent):
    """HttpTool uses camelCase inputSchema. Existing behavior must keep working."""
    from saz.tools.http_tool import HttpTool

    http_spec = HttpTool().spec
    assert "inputSchema" in http_spec
    required = set(http_spec["inputSchema"]["required"])
    assert {"method", "url"} <= required

    registry = {"http_request": http_spec}
    step = _make_step("http_request", args={"method": "GET"})  # missing url

    with pytest.raises(ValueError, match="url"):
        agent.ground(step, registry, current_data={}, run_id="r1")
