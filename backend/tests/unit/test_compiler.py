"""Unit tests for DSL compiler – YAML → Pydantic + JSON Schema + workflow spec."""

from typing import Any, cast

import pytest
from pydantic import ValidationError

from saz.compiler.dsl import (
    compile_dsl,
    compile_form_model,
    compile_policies,
    compile_workflow_spec,
    parse_yaml,
)

# ---------------------------------------------------------------------------
# parse_yaml
# ---------------------------------------------------------------------------


def test_parse_valid_yaml_minimal():
    yaml_content = """
_schema_version: 1
flow:
  name: TestFlow
  description: Minimal test workflow
workflow:
  planner_mode: deterministic
  steps:
    - id: s1
      type: noop
"""
    dsl = parse_yaml(yaml_content)
    assert dsl["flow"]["name"] == "TestFlow"
    assert "form" not in dsl
    assert len(dsl["workflow"]["steps"]) == 1


def test_parse_requires_schema_version():
    yaml_content = """
flow:
  name: TestFlow
workflow:
  steps: []
"""
    with pytest.raises(ValueError, match="schema_version: 1"):
        parse_yaml(yaml_content)


def test_parse_requires_flow_and_steps():
    yaml_no_flow = """
schema_version: 1
workflow: { steps: [ { id: s1, type: noop } ] }
"""
    with pytest.raises(ValueError, match="flow.name is required"):
        parse_yaml(yaml_no_flow)

    yaml_no_planner_mode = """
schema_version: 1
flow: { name: A, description: "Test workflow" }
workflow: { steps: [] }
"""
    with pytest.raises(ValueError, match="workflow.planner_mode is required"):
        parse_yaml(yaml_no_planner_mode)

    yaml_no_steps = """
schema_version: 1
flow: { name: A, description: "Test workflow" }
workflow: { planner_mode: deterministic }
"""
    with pytest.raises(ValueError, match="workflow.steps is required"):
        parse_yaml(yaml_no_steps)

    yaml_empty_steps = """
schema_version: 1
flow: { name: A, description: "Test workflow" }
workflow: { planner_mode: deterministic, steps: [] }
"""
    with pytest.raises(ValueError, match="non-empty"):
        parse_yaml(yaml_empty_steps)


def test_parse_form_optional_but_shape_checked():
    yaml_ok = """
schema_version: 1
flow: { name: A, description: "Test workflow" }
form: { fields: [] }
workflow: { planner_mode: deterministic, steps: [ { id: s1, type: noop } ] }
"""
    assert parse_yaml(yaml_ok)["form"]["fields"] == []

    yaml_bad = """
schema_version: 1
flow: { name: A, description: "Test workflow" }
form: {}
workflow: { planner_mode: deterministic, steps: [ { id: s1, type: noop } ] }
"""
    with pytest.raises(ValueError, match="form.fields is required"):
        parse_yaml(yaml_bad)


# ---------------------------------------------------------------------------
# compile_form_model (types/constraints)
# ---------------------------------------------------------------------------


def test_form_string_with_pattern_and_format_email():
    form_def = {
        "fields": [
            {
                "name": "email",
                "type": "string",
                "required": True,
                "format": "email",  # should auto-map to a pattern
                "description": "User email",
            }
        ]
    }
    model_cls, schema = compile_form_model(form_def)
    inst = model_cls(email="user@example.com")
    assert cast(Any, inst).email == "user@example.com"
    prop = schema["properties"]["email"]
    assert prop["type"] == "string"
    assert "pattern" in prop
    assert prop["description"] == "User email"

    with pytest.raises(ValidationError):
        model_cls(email="not-an-email")


def test_form_string_min_max_length_and_explicit_pattern():
    form_def = {
        "fields": [
            {
                "name": "username",
                "type": "string",
                "required": True,
                "minLength": 3,
                "maxLength": 12,
                "pattern": "^[a-z0-9_]+$",
            }
        ]
    }
    model_cls, _ = compile_form_model(form_def)
    model_cls(username="abc_123")
    with pytest.raises(ValidationError):
        model_cls(username="AB")  # too short + uppercase not allowed


def test_form_invalid_regex_raises_value_error():
    form_def = {
        "fields": [
            {
                "name": "weird",
                "type": "string",
                "required": True,
                "pattern": "(",
            }
        ]
    }
    with pytest.raises(ValueError, match="Invalid regex"):
        compile_form_model(form_def)


def test_form_number_and_integer_with_minimum_maximum():
    form_def = {
        "fields": [
            {"name": "age", "type": "integer", "required": True, "minimum": 18, "maximum": 120},
            {"name": "score", "type": "number", "required": True, "minimum": 0.0, "maximum": 1.0},
        ]
    }
    model_cls, schema = compile_form_model(form_def)

    ok = model_cls(age=30, score=0.5)
    assert cast(Any, ok).age == 30
    assert abs(cast(Any, ok).score - 0.5) < 1e-9

    with pytest.raises(ValidationError):
        model_cls(age=10, score=0.5)

    with pytest.raises(ValidationError):
        model_cls(age=30, score=2.0)

    assert schema["properties"]["age"]["minimum"] == 18
    assert schema["properties"]["age"]["maximum"] == 120
    assert schema["properties"]["score"]["minimum"] == 0.0
    assert schema["properties"]["score"]["maximum"] == 1.0


def test_form_boolean_and_optional_defaults_and_enum():
    form_def = {
        "fields": [
            {"name": "newsletter", "type": "boolean", "required": True},
            {"name": "nickname", "type": "string", "required": False, "default": None},
            {"name": "role", "type": "string", "required": True, "enum": ["user", "admin"]},
        ]
    }
    model_cls, schema = compile_form_model(form_def)
    inst = model_cls(newsletter=False, role="user")
    assert cast(Any, inst).nickname is None
    assert schema["properties"]["role"]["enum"] == ["user", "admin"]


def test_form_unknown_type_is_error():
    form_def = {"fields": [{"name": "x", "type": "unknown_type", "required": True}]}
    with pytest.raises(ValueError, match="Unsupported form field type"):
        compile_form_model(form_def)


# ---------------------------------------------------------------------------
# compile_workflow_spec (light wrapper) + deep checks handled in compile_dsl
# ---------------------------------------------------------------------------


def test_compile_workflow_spec_passthrough():
    workflow_def = {
        "planner_mode": "deterministic",
        "steps": [
            {"id": "s1", "type": "tool.call"},
            {"id": "s2", "type": "ai.extract", "instruction": "Do it"},
        ],
    }
    spec = compile_workflow_spec(workflow_def, "FlowName")
    assert spec["name"] == "FlowName"
    assert spec["planner_mode"] == "deterministic"
    assert [s["id"] for s in spec["steps"]] == ["s1", "s2"]


# ---------------------------------------------------------------------------
# compile_policies (normalization)
# ---------------------------------------------------------------------------


def test_compile_policies_defaults_shape():
    pol = compile_policies(None)
    assert pol["budget_usd"] == 10.0
    assert pol["defaults"]["timeout_ms"] == 15000
    assert pol["defaults"]["continue_on_fail"] is False
    assert pol["defaults"]["retry"] == {}
    assert pol["pii"]["allow"] is False
    assert isinstance(pol["rate_limits"], dict)


def test_compile_policies_overrides():
    pol = compile_policies(
        {
            "budget_usd": 3.5,
            "concurrency": {"per_flow": 2},
            "defaults": {
                "timeout_ms": 5000,
                "continue_on_fail": True,
                "retry": {"attempts": 2, "backoff": {"mode": "exponential", "base_ms": 100}},
            },
            "pii": {"allow": True},
            "rate_limits": {"http_request": {"rpm": 120}},
        }
    )
    assert pol["budget_usd"] == 3.5
    assert pol["concurrency"]["per_flow"] == 2
    assert pol["defaults"]["timeout_ms"] == 5000
    assert pol["defaults"]["continue_on_fail"] is True
    assert pol["defaults"]["retry"]["attempts"] == 2
    assert pol["defaults"]["retry"]["backoff"]["mode"] == "exponential"
    assert pol["pii"]["allow"] is True
    assert pol["rate_limits"]["http_request"]["rpm"] == 120


def test_compile_policies_validation_errors():
    with pytest.raises(ValueError, match="budget_usd"):
        compile_policies({"budget_usd": -1})

    with pytest.raises(ValueError, match="concurrency.per_flow"):
        compile_policies({"concurrency": {"per_flow": 0}})

    with pytest.raises(ValueError, match="backoff.mode"):
        compile_policies({"defaults": {"retry": {"backoff": {"mode": "bad"}}}})


# ---------------------------------------------------------------------------
# compile_dsl – workflow deep validation (all allowed step types)
# ---------------------------------------------------------------------------


def _base(prefix_steps: str) -> str:
    """Helper to wrap steps in a valid DSL document."""
    return f"""
schema_version: 1
flow:
  name: FlowX
  description: Test workflow
form:
  fields: []
workflow:
  planner_mode: deterministic
  steps:
{prefix_steps}
"""


def test_dsl_tool_call_and_ai_steps_and_credentials_ok():
    yaml_content = """
schema_version: 1
flow: { name: FlowX, description: "Test workflow" }
credentials:
  uses: [github, slack]
workflow:
  planner_mode: deterministic
  steps:
    - id: t1
      type: tool.call
      description: "Test step"
      tool: http_request
      params: { url: "https://example.com", method: "GET" }
      uses_credentials: ["github"]
    - id: a1
      type: ai.extract
      instruction: "Extract data"
      expect: { type: object, properties: { x: { type: string } } }
"""
    compiled = compile_dsl(yaml_content)
    ids = [s["id"] for s in compiled.workflow_spec["steps"]]
    assert ids == ["t1", "a1"]
    assert compiled.credentials == ["github", "slack"]


def test_dsl_condition_and_human_and_webhook_and_artifacts():
    steps = """
    - id: c1
      type: condition
      description: "Test step"
      if: "${{ input.value > 0 }}"
    - id: h1
      type: human.approval
      description: "Test step"
      params: { approvers: ["alice"] }
    - id: w1
      type: webhook.wait
      description: "Test step"
      params: { event_name: "payment.succeeded" }
    - id: s1
      type: artifact.store
      description: "Test step"
      params: { name: "doc", content: "hello" }
    - id: r1
      type: artifact.retrieve
      description: "Test step"
      params: { name: "doc" }
"""
    compiled = compile_dsl(_base(steps))
    assert [s["type"] for s in compiled.workflow_spec["steps"]] == [
        "condition",
        "human.approval",
        "webhook.wait",
        "artifact.store",
        "artifact.retrieve",
    ]


def test_dsl_rejects_group_and_noop_step_types():
    """group.parallel, group.map, and noop are no longer compiler-allowed.

    Historically the compiler accepted these but the executor never
    implemented them — flows compiled fine and crashed with
    'Unknown step_type' at runtime. The compiler now matches the runtime.
    """
    for stype in ("group.parallel", "group.map", "noop"):
        with pytest.raises(ValueError, match="Unknown step type"):
            compile_dsl(_base(f"    - id: x1\n      type: {stype}\n"))


# ---------------------------------------------------------------------------
# compile_dsl – failure cases (shape + cross-references)
# ---------------------------------------------------------------------------


def test_dsl_unknown_step_type_raises():
    steps = """
    - id: bad
      type: totally.unknown
"""
    with pytest.raises(ValueError, match="Unknown step type"):
        compile_dsl(_base(steps))


def test_dsl_missing_required_keys_per_type():
    with pytest.raises(ValueError, match="missing key: tool"):
        compile_dsl(
            _base(
                """
    - id: t1
      type: tool.call
      description: "Test step"
      params: {}
"""
            )
        )

    with pytest.raises(ValueError, match="requires.*instruction"):
        compile_dsl(
            _base(
                """
    - id: a1
      type: ai.extract
"""
            )
        )


def test_dsl_params_must_be_object_when_present():
    with pytest.raises(ValueError, match="params must be an object"):
        compile_dsl(
            _base(
                """
    - id: t1
      type: tool.call
      description: "Test step"
      tool: http_request
      params: 42
"""
            )
        )

    with pytest.raises(ValueError, match="webhook.wait requires params.event_name"):
        compile_dsl(
            _base(
                """
    - id: w1
      type: webhook.wait
      description: "Test step"
      params: {}
"""
            )
        )


def test_dsl_duplicate_step_ids_disallowed():
    with pytest.raises(ValueError, match="Duplicate step id"):
        compile_dsl(
            _base(
                """
    - id: s
      type: human.approval
      description: "Filler step"
    - id: s
      type: human.approval
      description: "Duplicate id"
"""
            )
        )


def test_dsl_uses_credentials_must_exist_and_be_list():
    doc = """
schema_version: 1
flow: { name: FlowX, description: "Test workflow" }
credentials:
  uses: [known]
workflow:
  planner_mode: deterministic
  steps:
    - id: t1
      type: tool.call
      description: "Test step"
      tool: http_request
      params: {}
      uses_credentials: ["known", "missing"]
"""
    with pytest.raises(ValueError, match="unknown credentials"):
        compile_dsl(doc)

    doc2 = """
schema_version: 1
flow: { name: FlowX, description: "Test workflow" }
credentials:
  uses: [known]
workflow:
  planner_mode: deterministic
  steps:
    - id: t1
      type: tool.call
      description: "Test step"
      tool: http_request
      params: {}
      uses_credentials: "known"
"""
    with pytest.raises(ValueError, match="string list"):
        compile_dsl(doc2)


def test_dsl_retry_and_backoff_validation():
    # attempts < 0
    with pytest.raises(ValueError, match="attempts must be >= 0"):
        compile_dsl(
            _base(
                """
    - id: t1
      type: tool.call
      description: "Test step"
      tool: http_request
      params: {}
      retry: { attempts: -1 }
"""
            )
        )
    # bad backoff mode
    with pytest.raises(ValueError, match="backoff.mode"):
        compile_dsl(
            _base(
                """
    - id: t1
      type: tool.call
      description: "Test step"
      tool: http_request
      params: {}
      retry: { attempts: 1, backoff: { mode: "bad" } }
"""
            )
        )
    # negative base_ms
    with pytest.raises(ValueError, match="backoff.base_ms"):
        compile_dsl(
            _base(
                """
    - id: t1
      type: tool.call
      description: "Test step"
      tool: http_request
      params: {}
      retry: { attempts: 1, backoff: { mode: "linear", base_ms: -1 } }
"""
            )
        )
    # jitter must be bool
    with pytest.raises(ValueError, match="jitter must be boolean"):
        compile_dsl(
            _base(
                """
    - id: t1
      type: tool.call
      description: "Test step"
      tool: http_request
      params: {}
      retry: { attempts: 1, backoff: { mode: "linear", jitter: "yes" } }
"""
            )
        )


# ---------------------------------------------------------------------------
# Full integration happy-path
# ---------------------------------------------------------------------------


def test_full_integration():
    yaml_content = """
schema_version: 1
flow:
  name: UserOnboarding
  version: "1.0"
  description: Onboard new users
  labels: { domain: "user", stage: "prod" }
  owners: ["team-a@example.com"]

form:
  fields:
    - name: email
      type: string
      required: true
      format: email
    - name: age
      type: integer
      required: true
      minimum: 18
      maximum: 120

credentials:
  uses: [github_token, slack_webhook]

policies:
  budget_usd: 5.0
  defaults:
    timeout_ms: 10000
    retry: { attempts: 1, backoff: { mode: exponential, base_ms: 100, jitter: true } }
  pii: { allow: true }
  rate_limits:
    http_request: { rpm: 120 }

workflow:
  planner_mode: deterministic
  steps:
    - id: validate_email
      type: tool.call
      tool: http_request
      params: { url: "https://example.com/validate", method: "GET" }
      description: Validate email address
      uses_credentials: [ "github_token" ]

    - id: assess_risk
      type: ai.extract
      instruction: "Assess user risk level"
      expect:
        type: object
        properties:
          risk: { type: string, enum: ["low", "medium", "high"] }
        required: ["risk"]
"""
    compiled = compile_dsl(yaml_content)

    # Flow meta
    assert compiled.flow_name == "UserOnboarding"
    assert compiled.flow_version == "1.0"
    assert compiled.flow_description == "Onboard new users"

    # Form model & schema
    instance = compiled.form_model(email="test@example.com", age=25)
    assert cast(Any, instance).email == "test@example.com"
    assert cast(Any, instance).age == 25
    assert "email" in compiled.form_schema["properties"]
    assert "age" in compiled.form_schema["properties"]

    # Policies normalized
    pol = compiled.policies
    assert pol["budget_usd"] == 5.0
    assert pol["defaults"]["timeout_ms"] == 10000
    assert pol["defaults"]["retry"]["attempts"] == 1
    assert pol["defaults"]["retry"]["backoff"]["mode"] == "exponential"
    assert pol["pii"]["allow"] is True
    assert pol["rate_limits"]["http_request"]["rpm"] == 120

    # Workflow spec
    steps = compiled.workflow_spec["steps"]
    assert steps[0]["id"] == "validate_email"
    assert steps[0]["type"] == "tool.call"
    assert steps[1]["type"] == "ai.extract"

    # Credentials
    assert set(compiled.credentials) == {"github_token", "slack_webhook"}
