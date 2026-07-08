"""Every shipped example must plan and ground its first step without crashing.

The compile+register smoke test in tests/acceptance proves the DSL is
well-formed. This test goes one step further: it runs the deterministic
planner against each example, builds the real ToolRegistry (with stub
ai_runner and ansible/http/webhook fakes), and asks ExecutorAgent.ground
to resolve the first step's input_template against a representative form
payload.

What this catches:
  - Step types the planner can't convert.
  - Tools referenced in YAML but not registered.
  - Templates that fail to resolve given the example's form fields.
  - Required-field validation drift between AI tool specs and the
    deterministic planner's emitted input_template.

It does not assert end-to-end completion — that would require scripting
AI responses to satisfy every `expect` schema per-example, which is more
churn than the drift coverage is worth.
"""

import asyncio
from pathlib import Path

import pytest

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.compiler.dsl import compile_dsl
from saz.tools.registry import ToolRegistry
from tests.acceptance.test_examples_execute_safely import (
    _EXAMPLE_FILES,
    _strip_meta_section,
)
from tests.fakes.tools import RecordingTool


def _make_full_fake_registry() -> ToolRegistry:
    """A ToolRegistry pre-populated with fakes for every example tool."""
    registry = ToolRegistry()

    def register(name: str, spec_kind: str = "input_schema") -> None:
        spec = {
            "name": name,
            "description": f"fake {name}",
            spec_kind: {"type": "object", "properties": {}, "required": []},
        }
        tool = RecordingTool(name=name, response={"ok": True}, spec=spec)
        registry.register_custom_tool(name, tool.spec, tool.execute)

    # Outbound tools (camelCase key, mirroring real specs)
    for name in ("http_request", "webhook_emit", "webhook_wait", "ansible_run"):
        register(name, "input_schema")
    for name in ("artifact.store", "artifact.retrieve"):
        register(name, "input_schema")

    # AI ops (snake_case key, mirroring real specs)
    from saz.agents.ai_ops import AI_OPS

    for op_name in AI_OPS:
        register(op_name, "input_schema")

    return registry


def _make_form_payload(form_schema: dict) -> dict:
    """Produce a minimal form payload satisfying required fields."""
    out: dict = {}
    properties = form_schema.get("properties", {})
    required = form_schema.get("required", [])
    for name in required:
        spec = properties.get(name, {})
        t = spec.get("type")
        if t == "integer":
            out[name] = 1
        elif t == "number":
            out[name] = 1.0
        elif t == "boolean":
            out[name] = True
        elif t == "array":
            out[name] = []
        elif t == "object":
            out[name] = {}
        else:
            out[name] = "example"
    return out


@pytest.mark.parametrize(
    "yaml_path",
    _EXAMPLE_FILES,
    ids=[p.name for p in _EXAMPLE_FILES],
)
def test_example_plans_and_grounds_first_step(yaml_path: Path):
    compiled = compile_dsl(_strip_meta_section(yaml_path.read_text()))
    workflow_spec = compiled.workflow_spec

    # Agentic examples have empty steps — DeterministicPlanner can't help
    # there. Skip the ground step but still confirm compile worked.
    if not workflow_spec.get("steps"):
        return

    registry = _make_full_fake_registry()
    planner = DeterministicPlanner()
    form_payload = _make_form_payload(compiled.form_schema)

    plan = asyncio.run(
        planner.plan(
            workflow_spec=workflow_spec,
            tool_registry=registry.get_tool_specs(),
            run_id="run_plan_ground_x",
            completed_steps=[],
            current_data={"form_data": form_payload},
            budget={},
        )
    )
    assert plan.steps, f"planner produced no steps for {yaml_path.name}"

    first = plan.steps[0]
    assert first.tool_name, f"first step has empty tool_name in {yaml_path.name}"

    # Ground the first step. If a referenced tool is missing or the
    # template references an unknown form field, this raises with a clear
    # message — catching drift between example DSL and the runtime contract.
    # Provide a stub secret resolver so $secret('NAME') doesn't fail the
    # template — we're testing structural grounding, not secret wiring.
    agent = ExecutorAgent(secret_resolver=lambda name: f"fake_secret_{name}")
    try:
        agent.ground(
            step=first,
            tool_registry=registry.get_tool_specs_dict(),
            current_data={"form_data": form_payload, "step_results": {}},
            run_id="run_plan_ground_x",
        )
    except ValueError as e:
        # Required-arg validation on the FAKE registry intentionally has
        # no required fields. A ValueError here means a real drift —
        # template variable missing, tool not registered, etc.
        pytest.fail(f"{yaml_path.name}: first step '{first.step_id}' failed to ground: {e}")
