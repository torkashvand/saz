"""Tests for DSL validation (instruction/description requirements)."""

import pytest

from saz.compiler.dsl import compile_dsl


def test_flow_description_required():
    """Test that flow.description is required."""
    yaml_content = """
schema_version: 1
flow:
  name: test_flow
  # Missing description
workflow:
  planner_mode: deterministic
  steps:
    - id: step1
      type: tool.call
      description: Test step
      tool: http_request
      params: {}
"""
    with pytest.raises(ValueError) as exc_info:
        compile_dsl(yaml_content)

    assert "flow.description is required" in str(exc_info.value)


def test_flow_description_non_empty():
    """Test that flow.description must be non-empty."""
    yaml_content = """
schema_version: 1
flow:
  name: test_flow
  description: ""
workflow:
  planner_mode: deterministic
  steps:
    - id: step1
      type: tool.call
      description: Test step
      tool: http_request
      params: {}
"""
    with pytest.raises(ValueError) as exc_info:
        compile_dsl(yaml_content)

    assert "flow.description is required" in str(exc_info.value)


def test_tool_call_requires_description():
    """Test that tool.call steps require description."""
    yaml_content = """
schema_version: 1
flow:
  name: test_flow
  description: Test workflow
workflow:
  planner_mode: deterministic
  steps:
    - id: call_api
      type: tool.call
      tool: http_request
      params:
        url: https://api.example.com
"""
    with pytest.raises(ValueError) as exc_info:
        compile_dsl(yaml_content)

    assert "call_api" in str(exc_info.value)
    assert "tool.call" in str(exc_info.value)
    assert "description" in str(exc_info.value)


def test_ai_step_requires_instruction():
    """Test that ai.* steps require instruction."""
    yaml_content = """
schema_version: 1
flow:
  name: test_flow
  description: Test workflow
workflow:
  planner_mode: deterministic
  steps:
    - id: extract_data
      type: ai.extract
      params:
        data:
          text: hello
"""
    with pytest.raises(ValueError) as exc_info:
        compile_dsl(yaml_content)

    assert "extract_data" in str(exc_info.value)
    assert "ai.extract" in str(exc_info.value)
    assert "instruction" in str(exc_info.value)


def test_condition_requires_description():
    """Test that condition steps require description."""
    yaml_content = """
schema_version: 1
flow:
  name: test_flow
  description: Test workflow
workflow:
  planner_mode: deterministic
  steps:
    - id: check_status
      type: condition
      if: "{{ $form.enabled }} == true"
"""
    with pytest.raises(ValueError) as exc_info:
        compile_dsl(yaml_content)

    assert "check_status" in str(exc_info.value)
    assert "condition" in str(exc_info.value)
    assert "description" in str(exc_info.value)


def test_human_approval_requires_description():
    """Test that human.approval steps require description."""
    yaml_content = """
schema_version: 1
flow:
  name: test_flow
  description: Test workflow
workflow:
  planner_mode: deterministic
  steps:
    - id: approve_deploy
      type: human.approval
      params:
        approval_required_from: ops_team
"""
    with pytest.raises(ValueError) as exc_info:
        compile_dsl(yaml_content)

    assert "approve_deploy" in str(exc_info.value)
    assert "human.approval" in str(exc_info.value)
    assert "description" in str(exc_info.value)


def test_artifact_store_requires_description():
    """Test that artifact.store steps require description."""
    yaml_content = """
schema_version: 1
flow:
  name: test_flow
  description: Test workflow
workflow:
  planner_mode: deterministic
  steps:
    - id: save_results
      type: artifact.store
      params:
        name: results
        content: {}
"""
    with pytest.raises(ValueError) as exc_info:
        compile_dsl(yaml_content)

    assert "save_results" in str(exc_info.value)
    assert "artifact.store" in str(exc_info.value)
    assert "description" in str(exc_info.value)


def test_webhook_wait_requires_description():
    """Test that webhook.wait steps require description."""
    yaml_content = """
schema_version: 1
flow:
  name: test_flow
  description: Test workflow
workflow:
  planner_mode: deterministic
  steps:
    - id: wait_callback
      type: webhook.wait
      params:
        event_name: deployment_complete
"""
    with pytest.raises(ValueError) as exc_info:
        compile_dsl(yaml_content)

    assert "wait_callback" in str(exc_info.value)
    assert "webhook.wait" in str(exc_info.value)
    assert "description" in str(exc_info.value)


def test_valid_workflow_with_all_intents():
    """Test that valid workflow with all intent fields compiles successfully."""
    yaml_content = """
schema_version: 1
flow:
  name: test_flow
  description: Complete test workflow
workflow:
  planner_mode: deterministic
  steps:
    - id: plan
      type: ai.generate
      instruction: Generate deployment plan
      expect:
        type: object
        properties:
          output: { type: string }
        required: [output]
      params:
        data: {}
    - id: execute
      type: tool.call
      description: Execute deployment
      tool: ansible_run
      params:
        mode: check
        playbook: deploy.yml
        inventory: hosts.ini
    - id: check
      type: condition
      description: Verify success
      if: "true"
    - id: approve
      type: human.approval
      description: Get approval
    - id: store
      type: artifact.store
      description: Save results
      params:
        name: results
        content: {}
"""
    result = compile_dsl(yaml_content)
    assert result.flow_name == "test_flow"
    assert result.flow_description == "Complete test workflow"
    assert len(result.workflow_spec["steps"]) == 5


def test_empty_instruction_fails():
    """Test that empty instruction string fails validation."""
    yaml_content = """
schema_version: 1
flow:
  name: test_flow
  description: Test workflow
workflow:
  planner_mode: deterministic
  steps:
    - id: extract
      type: ai.extract
      instruction: ""
      params:
        data: {}
"""
    with pytest.raises(ValueError) as exc_info:
        compile_dsl(yaml_content)

    assert "instruction" in str(exc_info.value)


def test_empty_description_fails():
    """Test that empty description string fails validation."""
    yaml_content = """
schema_version: 1
flow:
  name: test_flow
  description: Test workflow
workflow:
  planner_mode: deterministic
  steps:
    - id: call_api
      type: tool.call
      description: ""
      tool: http_request
      params: {}
"""
    with pytest.raises(ValueError) as exc_info:
        compile_dsl(yaml_content)

    assert "description" in str(exc_info.value)


def _compile(steps_yaml: str):
    return compile_dsl(
        """
schema_version: 1
flow:
  name: dsl_gap_flow
  description: DSL gap coverage
workflow:
  planner_mode: deterministic
  steps:
"""
        + steps_yaml
    )


def test_unknown_step_key_warns_not_silently_dropped():
    """A misspelled extra key (branch_enum vs branches_enum) must surface as a
    compile warning instead of being silently dropped by additionalProperties."""
    compiled = _compile(
        """
    - id: route_it
      type: ai.route
      description: route the request
      instruction: choose a branch
      expect: {type: object}
      branch_enum: [a, b]
"""
    )
    blob = " ".join(compiled.warnings)
    assert "branch_enum" in blob, f"typo'd key not warned: {compiled.warnings}"
    assert "route_it" in blob


def test_known_ai_extras_do_not_warn():
    """Declared AI extras must compile clean (no false-positive warnings)."""
    compiled = _compile(
        """
    - id: gen
      type: ai.generate
      description: write a summary
      instruction: summarize
      expect: {type: object}
      temperature: 0.2
      max_tokens: 256
      word_cap: 100
"""
    )
    assert compiled.warnings == [], compiled.warnings


def test_webhook_wait_timeout_must_be_positive():
    with pytest.raises(ValueError) as exc:
        _compile(
            """
    - id: wait
      type: webhook.wait
      description: wait for callback
      params:
        event_name: done
        timeout_minutes: -5
"""
        )
    assert "timeout_minutes" in str(exc.value)


def test_webhook_wait_valid_timeout_compiles():
    compiled = _compile(
        """
    - id: wait
      type: webhook.wait
      description: wait for callback
      params:
        event_name: done
        timeout_seconds: 30
"""
    )
    assert compiled.warnings == [], compiled.warnings
