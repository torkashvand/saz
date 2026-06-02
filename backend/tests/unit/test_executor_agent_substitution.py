"""Tests for ExecutorAgent.ground() variable substitution.

``ground()`` is the surface the workflow executor calls to turn a planned
step into a concrete ToolCall. It delegates resolution to
``saz.engine.templating.resolve_template`` and adds tool-spec validation
and idempotency-key construction on top.

These tests pin:

  * nested $form / $step / $env resolution propagated into the ToolCall,
  * idempotency_key shape so dedup at the tool layer stays correct,
  * tool-not-in-registry errors,
  * required-arg validation under both ``inputSchema`` and ``input_schema``
    keys (the registry is inconsistent and the executor must accept both).
"""

from typing import Any

import pytest

from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import ErrorHandling, PlanStep


@pytest.fixture
def agent() -> ExecutorAgent:
    return ExecutorAgent()


def _step(
    tool_name: str = "http_request",
    input_template: dict[str, Any] | None = None,
    *,
    step_id: str = "s1",
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        step_type="tool.call",
        tool_name=tool_name,
        input_template=input_template or {},
        expected_output_schema={"type": "object"},
        error_handling=ErrorHandling.RETRY,
        max_retries=0,
        reasoning="test",
    )


# ---------------- substitution propagation ----------------


def test_ground_resolves_form_values_in_nested_payload(agent: ExecutorAgent) -> None:
    registry = {
        "http_request": {
            "name": "http_request",
            "inputSchema": {"required": ["url", "method"]},
        }
    }
    step = _step(
        "http_request",
        {
            "method": "POST",
            "url": "{{ $form.target }}",
            "body": {"recipient": "{{ $form.user.email }}"},
        },
    )
    call = agent.ground(
        step,
        registry,
        current_data={
            "form_data": {
                "target": "https://api.test/notify",
                "user": {"email": "a@b.com"},
            }
        },
        run_id="run-1",
    )
    assert call.arguments["method"] == "POST"
    assert call.arguments["url"] == "https://api.test/notify"
    assert call.arguments["body"] == {"recipient": "a@b.com"}


def test_ground_resolves_step_outputs_in_nested_payload(agent: ExecutorAgent) -> None:
    registry = {
        "http_request": {
            "name": "http_request",
            "inputSchema": {"required": ["url"]},
        }
    }
    step = _step(
        "http_request",
        {
            "url": "https://api.test/next",
            "tags": ["{{ $step('extract').category }}"],
        },
    )
    call = agent.ground(
        step,
        registry,
        current_data={
            "step_results": {"extract": {"output": {"category": "billing"}}},
        },
        run_id="run-1",
    )
    assert call.arguments["tags"] == ["billing"]


def test_ground_resolves_env_values(agent: ExecutorAgent, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_API", "https://prod.test")
    registry = {
        "http_request": {
            "name": "http_request",
            "inputSchema": {"required": ["url"]},
        }
    }
    step = _step("http_request", {"url": "{{ $env('MY_API') }}/x"})
    call = agent.ground(step, registry, current_data={}, run_id="run-1")
    assert call.arguments["url"] == "https://prod.test/x"


# ---------------- idempotency key + rationale ----------------


def test_ground_builds_idempotency_key_from_run_id_and_step_id(
    agent: ExecutorAgent,
) -> None:
    registry = {
        "http_request": {
            "name": "http_request",
            "inputSchema": {"required": []},
        }
    }
    step = _step("http_request", {"url": "https://x.test"}, step_id="step-a")
    call = agent.ground(step, registry, current_data={}, run_id="run-XYZ")
    assert call.idempotency_key == "run-XYZ:step-a"
    assert call.tool == "http_request"
    assert "step-a" in call.rationale


# ---------------- error paths ----------------


def test_ground_raises_when_tool_not_in_registry(agent: ExecutorAgent) -> None:
    with pytest.raises(ValueError, match="not found in registry"):
        agent.ground(_step("ghost"), tool_registry={}, current_data={}, run_id="r1")


def test_ground_validates_required_fields_under_input_schema_snake_case(
    agent: ExecutorAgent,
) -> None:
    """Snake-case ``input_schema`` is what the AI-ops and Ansible specs use.
    The validator must read it the same way it reads camelCase."""
    registry = {
        "snake": {
            "name": "snake",
            "input_schema": {"required": ["essential"]},
        }
    }
    step = _step("snake", {"some_other_field": 1})
    with pytest.raises(ValueError, match="essential"):
        agent.ground(step, registry, current_data={}, run_id="r1")


def test_ground_validates_required_fields_under_inputSchema_camel_case(
    agent: ExecutorAgent,
) -> None:
    registry = {
        "camel": {
            "name": "camel",
            "inputSchema": {"required": ["url"]},
        }
    }
    step = _step("camel", {"method": "GET"})
    with pytest.raises(ValueError, match="url"):
        agent.ground(step, registry, current_data={}, run_id="r1")


def test_ground_passes_when_required_fields_satisfied_by_template_resolution(
    agent: ExecutorAgent,
) -> None:
    """The required-field check runs AFTER template resolution — a templated
    value that resolves to a real value must satisfy the requirement."""
    registry = {
        "http_request": {
            "name": "http_request",
            "input_schema": {"required": ["url"]},
        }
    }
    step = _step("http_request", {"url": "{{ $form.target }}"})
    call = agent.ground(
        step,
        registry,
        current_data={"form_data": {"target": "https://x.test"}},
        run_id="r1",
    )
    assert call.arguments["url"] == "https://x.test"


# ---------------- argument schema validation (enum / unresolved) ----------------


def test_ground_rejects_invalid_enum_value(agent: ExecutorAgent) -> None:
    registry = {
        "http_request": {
            "name": "http_request",
            "input_schema": {
                "required": ["method", "url"],
                "properties": {"method": {"enum": ["GET", "POST"]}},
            },
        }
    }
    step = _step("http_request", {"method": "FETCH", "url": "https://x.test"})
    with pytest.raises(ValueError, match="not in"):
        agent.ground(step, registry, current_data={}, run_id="r1")


def test_ground_accepts_valid_enum_value(agent: ExecutorAgent) -> None:
    registry = {
        "http_request": {
            "name": "http_request",
            "input_schema": {
                "required": ["method", "url"],
                "properties": {"method": {"enum": ["GET", "POST"]}},
            },
        }
    }
    step = _step("http_request", {"method": "POST", "url": "https://x.test"})
    call = agent.ground(step, registry, current_data={}, run_id="r1")
    assert call.arguments["method"] == "POST"


def test_ground_rejects_unresolved_template(agent: ExecutorAgent) -> None:
    registry = {
        "http_request": {
            "name": "http_request",
            "input_schema": {"required": ["url"]},
        }
    }
    # An unrecognized expression survives grounding as a literal "{{ ... }}".
    step = _step("http_request", {"url": "{{ coalesce($form.a) }}"})
    with pytest.raises(ValueError, match="Unresolved template"):
        agent.ground(step, registry, current_data={}, run_id="r1")
