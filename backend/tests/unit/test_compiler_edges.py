"""Edge-case tests for saz.compiler.dsl.

The bulk of compiler behavior is covered by tests/unit/test_compiler.py.
This file fills the gaps the coverage report flagged:

  * legacy alias normalization (_schema_version, regex/min/max),
  * malformed YAML and non-dict roots,
  * per-step-type required-field errors (description, instruction, expect,
    params, event_name),
  * unknown / disallowed step types,
  * retry shape validation,
  * credential and policy shape errors,
  * form field type / regex validation.
"""

import pytest

from saz.compiler.dsl import (
    _normalize_pre_schema,
    compile_dsl,
    compile_form_model,
    compile_policies,
    parse_yaml,
)

# ----------------------------- pre-schema normalisation -----------------------------


def test_normalize_pre_schema_promotes_schema_version_aliases() -> None:
    dsl1 = _normalize_pre_schema({"_schema_version": 1, "flow": {}})
    dsl2 = _normalize_pre_schema({"schemaVersion": 1, "flow": {}})
    assert dsl1["schema_version"] == 1
    assert "_schema_version" not in dsl1
    assert dsl2["schema_version"] == 1
    assert "schemaVersion" not in dsl2


def test_normalize_pre_schema_coerces_string_one_to_int() -> None:
    dsl = _normalize_pre_schema({"schema_version": "1"})
    assert dsl["schema_version"] == 1


def test_normalize_pre_schema_normalizes_form_field_aliases() -> None:
    dsl = _normalize_pre_schema(
        {
            "schema_version": 1,
            "form": {
                "fields": [
                    {"name": "x", "type": "text", "regex": r"^\d+$"},
                    {"name": "y", "type": "int", "min": 1, "max": 9},
                    {"name": "z", "type": "float"},
                ]
            },
        }
    )
    fields = dsl["form"]["fields"]
    assert fields[0]["type"] == "string"
    assert fields[0]["pattern"] == r"^\d+$"
    assert "regex" not in fields[0]

    assert fields[1]["type"] == "integer"
    assert fields[1]["minimum"] == 1
    assert fields[1]["maximum"] == 9
    assert "min" not in fields[1] and "max" not in fields[1]

    assert fields[2]["type"] == "number"


def test_normalize_pre_schema_skips_non_dict_field_entries() -> None:
    # A bad field entry must not cause normalisation to crash; the
    # downstream JSON-Schema check is what flags the error.
    dsl = _normalize_pre_schema(
        {
            "schema_version": 1,
            "form": {"fields": ["not-a-dict", {"name": "ok", "type": "text"}]},
        }
    )
    assert dsl["form"]["fields"][1]["type"] == "string"


# ----------------------------- parse_yaml errors -----------------------------


def test_parse_yaml_rejects_invalid_syntax() -> None:
    with pytest.raises(ValueError, match="Invalid YAML syntax"):
        parse_yaml("flow:\n  name: A\n  : badcolon\n")


def test_parse_yaml_rejects_non_dict_root() -> None:
    with pytest.raises(ValueError, match="YAML root must be a dictionary"):
        parse_yaml("[1, 2, 3]\n")


def test_parse_yaml_rejects_missing_flow_description() -> None:
    yaml_content = """
schema_version: 1
flow:
  name: TestFlow
workflow:
  planner_mode: deterministic
  steps:
    - id: s1
      type: condition
      if: "true"
      description: pass-through
"""
    with pytest.raises(ValueError, match="flow.description is required"):
        parse_yaml(yaml_content)


def test_parse_yaml_rejects_invalid_planner_mode() -> None:
    yaml_content = """
schema_version: 1
flow: { name: A, description: "Test workflow" }
workflow:
  planner_mode: magical
  steps: []
"""
    with pytest.raises(ValueError, match="planner_mode must be"):
        parse_yaml(yaml_content)


def test_parse_yaml_allows_empty_steps_for_agentic_planner() -> None:
    yaml_content = """
schema_version: 1
flow: { name: A, description: "Test workflow" }
workflow:
  planner_mode: agentic
  steps: []
"""
    dsl = parse_yaml(yaml_content)
    assert dsl["workflow"]["steps"] == []


def test_parse_yaml_rejects_form_without_fields() -> None:
    yaml_content = """
schema_version: 1
flow: { name: A, description: "Test workflow" }
form: { description: "no fields key" }
workflow:
  planner_mode: deterministic
  steps:
    - id: s1
      type: condition
      if: "true"
      description: x
"""
    with pytest.raises(ValueError, match="form.fields is required"):
        parse_yaml(yaml_content)


# ----------------------------- per-step-type validation -----------------------------


def _wrap(step_yaml: str) -> str:
    return f"""
schema_version: 1
flow: {{ name: A, description: "Test workflow" }}
workflow:
  planner_mode: deterministic
  steps:
{step_yaml}
"""


def test_compile_dsl_rejects_unknown_step_type() -> None:
    with pytest.raises(ValueError, match="Unknown step type 'mystery'"):
        compile_dsl(_wrap("    - id: s1\n      type: mystery\n      description: nope\n"))


def test_compile_dsl_rejects_tool_call_without_description() -> None:
    with pytest.raises(ValueError, match="tool.call.*description"):
        compile_dsl(
            _wrap(
                "    - id: s1\n"
                "      type: tool.call\n"
                "      tool: http_request\n"
                "      params: { method: GET, url: 'https://example.com' }\n"
            )
        )


def test_compile_dsl_rejects_tool_call_with_non_object_params() -> None:
    with pytest.raises(ValueError, match="params must be an object"):
        compile_dsl(
            _wrap(
                "    - id: s1\n"
                "      type: tool.call\n"
                "      description: do thing\n"
                "      tool: http_request\n"
                "      params: \"not-an-object\"\n"
            )
        )


# ------------------- tool.call params vs the tool's input_schema -------------------
#
# Regression: a docx_render step without `output_name` compiled fine and only
# failed mid-run at grounding ("Missing required parameters"). Required params
# of default-registry tools must be enforced at compile time.


def test_compile_dsl_rejects_tool_call_missing_required_tool_params() -> None:
    with pytest.raises(ValueError, match=r"step 's1' tool 'docx_render'.*output_name"):
        compile_dsl(
            _wrap(
                "    - id: s1\n"
                "      type: tool.call\n"
                "      description: render the doc\n"
                "      tool: docx_render\n"
                "      params:\n"
                "        template: t.docx\n"
                "        values: { a: '{{ $form.x }}' }\n"
            )
        )


def test_compile_dsl_accepts_tool_call_with_all_required_tool_params() -> None:
    compiled = compile_dsl(
        _wrap(
            "    - id: s1\n"
            "      type: tool.call\n"
            "      description: render the doc\n"
            "      tool: docx_render\n"
            "      params:\n"
            "        template: t.docx\n"
            "        output_name: \"out_{{ $form.x }}\"\n"
            "        values: { a: '{{ $form.x }}' }\n"
        )
    )
    assert compiled.workflow_spec["steps"][0]["id"] == "s1"


def test_compile_dsl_reports_all_missing_required_tool_params() -> None:
    with pytest.raises(ValueError, match=r"\['method', 'url'\]"):
        compile_dsl(
            _wrap(
                "    - id: s1\n"
                "      type: tool.call\n"
                "      description: call an api\n"
                "      tool: http_request\n"
                "      params: {}\n"
            )
        )


def test_compile_dsl_leaves_unknown_tools_to_linter_and_grounding() -> None:
    """Tools outside the default catalog (custom registries) are not the
    compiler's to judge — their params must pass through untouched."""
    compiled = compile_dsl(
        _wrap(
            "    - id: s1\n"
            "      type: tool.call\n"
            "      description: custom tool\n"
            "      tool: some_custom_tool\n"
            "      params: {}\n"
        )
    )
    assert compiled.workflow_spec["steps"][0]["tool"] == "some_custom_tool"


def test_compile_dsl_rejects_ai_step_without_expect() -> None:
    with pytest.raises(ValueError, match=r"requires 'expect' field"):
        compile_dsl(
            _wrap(
                "    - id: s1\n" "      type: ai.extract\n" "      instruction: 'extract email'\n"
            )
        )


def test_compile_dsl_rejects_ai_step_without_instruction() -> None:
    with pytest.raises(ValueError, match="requires non-empty 'instruction'"):
        compile_dsl(
            _wrap("    - id: s1\n" "      type: ai.extract\n" "      expect: { type: object }\n")
        )


def test_compile_dsl_rejects_human_approval_without_description() -> None:
    with pytest.raises(ValueError, match="human.approval"):
        compile_dsl(_wrap("    - id: s1\n" "      type: human.approval\n"))


def test_compile_dsl_rejects_webhook_wait_without_event_name() -> None:
    with pytest.raises(ValueError, match="webhook.wait requires params.event_name"):
        compile_dsl(
            _wrap(
                "    - id: s1\n"
                "      type: webhook.wait\n"
                "      description: wait for callback\n"
                "      params: {}\n"
            )
        )


def test_compile_dsl_rejects_artifact_store_without_description() -> None:
    with pytest.raises(ValueError, match="artifact.store"):
        compile_dsl(
            _wrap(
                "    - id: s1\n"
                "      type: artifact.store\n"
                "      params: { name: r, content: {} }\n"
            )
        )


def test_compile_dsl_rejects_duplicate_step_ids() -> None:
    yaml_content = _wrap(
        "    - id: dup\n      type: condition\n      if: 'true'\n      description: a\n"
        "    - id: dup\n      type: condition\n      if: 'true'\n      description: b\n"
    )
    with pytest.raises(ValueError, match="Duplicate step id: dup"):
        compile_dsl(yaml_content)


def test_compile_dsl_rejects_non_string_step_id() -> None:
    """A numeric step id is rejected by the JSON-Schema pass with a clear
    path-prefixed error before reaching per-type validation."""
    yaml_content = _wrap(
        "    - id: 123\n" "      type: condition\n" "      if: 'true'\n" "      description: x\n"
    )
    with pytest.raises(ValueError) as exc:
        compile_dsl(yaml_content)
    msg = str(exc.value)
    assert "workflow/steps/0/id" in msg
    assert "string" in msg


def test_compile_dsl_rejects_step_with_unknown_credential_reference() -> None:
    yaml_content = """
schema_version: 1
flow: { name: A, description: "Test workflow" }
credentials:
  uses: [ "approved_secret" ]
workflow:
  planner_mode: deterministic
  steps:
    - id: s1
      type: tool.call
      description: needs auth
      tool: http_request
      params: { method: GET, url: 'https://example.com' }
      uses_credentials: [ "missing_secret" ]
"""
    with pytest.raises(ValueError, match="unknown credentials"):
        compile_dsl(yaml_content)


# ----------------------------- retry validation -----------------------------


def test_compile_dsl_rejects_retry_with_negative_attempts() -> None:
    yaml_content = _wrap(
        "    - id: s1\n"
        "      type: tool.call\n"
        "      description: do thing\n"
        "      tool: http_request\n"
        "      params: { method: GET, url: 'https://example.com' }\n"
        "      retry:\n"
        "        attempts: -1\n"
    )
    with pytest.raises(ValueError, match="retry.attempts must be >= 0"):
        compile_dsl(yaml_content)


def test_compile_dsl_rejects_retry_with_invalid_backoff_mode() -> None:
    yaml_content = _wrap(
        "    - id: s1\n"
        "      type: tool.call\n"
        "      description: do thing\n"
        "      tool: http_request\n"
        "      params: { method: GET, url: 'https://example.com' }\n"
        "      retry:\n"
        "        attempts: 1\n"
        "        backoff: { mode: zigzag }\n"
    )
    with pytest.raises(ValueError, match="backoff.mode"):
        compile_dsl(yaml_content)


def test_compile_dsl_rejects_retry_with_non_bool_jitter() -> None:
    yaml_content = _wrap(
        "    - id: s1\n"
        "      type: tool.call\n"
        "      description: do thing\n"
        "      tool: http_request\n"
        "      params: { method: GET, url: 'https://example.com' }\n"
        "      retry:\n"
        "        attempts: 1\n"
        "        backoff:\n"
        "          mode: linear\n"
        "          jitter: \"yes\"\n"
    )
    with pytest.raises(ValueError, match="jitter must be boolean"):
        compile_dsl(yaml_content)


# ----------------------------- credentials validation -----------------------------


def test_compile_dsl_rejects_credentials_without_uses_array() -> None:
    """The JSON-Schema pass blocks unknown keys under ``credentials`` before
    the credential-shape validator runs — either way the compile fails
    with a credentials-targeted error."""
    yaml_content = """
schema_version: 1
flow: { name: A, description: "Test workflow" }
credentials:
  name: x
workflow:
  planner_mode: deterministic
  steps:
    - id: s1
      type: condition
      if: "true"
      description: x
"""
    with pytest.raises(ValueError) as exc:
        compile_dsl(yaml_content)
    assert "credentials" in str(exc.value).lower()


def test_compile_credentials_directly_rejects_non_object() -> None:
    """Call the private helper through the public surface — passing a
    bare string to ``_compile_credentials`` must raise the shape error."""
    from saz.compiler.dsl import _compile_credentials

    with pytest.raises(ValueError, match="credentials must be an object"):
        _compile_credentials("just-a-string")


def test_compile_credentials_directly_rejects_non_string_uses() -> None:
    from saz.compiler.dsl import _compile_credentials

    with pytest.raises(ValueError, match="credentials.uses must be a list of strings"):
        _compile_credentials({"uses": [1, 2, 3]})


def test_compile_dsl_rejects_duplicate_credentials() -> None:
    yaml_content = """
schema_version: 1
flow: { name: A, description: "Test workflow" }
credentials:
  uses: [ "secret_a", "secret_a" ]
workflow:
  planner_mode: deterministic
  steps:
    - id: s1
      type: condition
      if: "true"
      description: x
"""
    with pytest.raises(ValueError, match="duplicate names"):
        compile_dsl(yaml_content)


# ----------------------------- policy validation -----------------------------


def test_compile_policies_rejects_negative_budget() -> None:
    with pytest.raises(ValueError, match="budget_usd"):
        compile_policies({"budget_usd": -1})


def test_compile_policies_rejects_concurrency_object_shape() -> None:
    with pytest.raises(ValueError, match="concurrency must be an object"):
        compile_policies({"concurrency": "lots"})


def test_compile_policies_rejects_zero_per_flow() -> None:
    with pytest.raises(ValueError, match="per_flow"):
        compile_policies({"concurrency": {"per_flow": 0}})


def test_compile_policies_defaults_apply_when_missing() -> None:
    out = compile_policies(None)
    assert out["budget_usd"] == 10.0
    assert out["defaults"]["timeout_ms"] == 15_000
    assert out["defaults"]["continue_on_fail"] is False
    assert out["max_replan_attempts"] == 3


# ----------------------------- form model validation -----------------------------


def test_compile_form_model_rejects_unsupported_type() -> None:
    with pytest.raises(ValueError, match="Unsupported form field type"):
        compile_form_model({"fields": [{"name": "x", "type": "bigint"}]})


def test_compile_form_model_rejects_invalid_regex() -> None:
    with pytest.raises(ValueError, match="Invalid regex"):
        compile_form_model(
            {"fields": [{"name": "x", "type": "string", "pattern": "[unterminated"}]}
        )


def test_compile_form_model_rejects_non_dict_field_entry() -> None:
    with pytest.raises(ValueError, match="items must be objects"):
        compile_form_model({"fields": ["not-a-dict"]})


def test_compile_form_model_rejects_field_missing_name_or_type() -> None:
    with pytest.raises(ValueError, match="requires 'name' and 'type'"):
        compile_form_model({"fields": [{"type": "string"}]})
