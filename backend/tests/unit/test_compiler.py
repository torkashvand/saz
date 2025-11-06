"""Unit tests for DSL compiler - YAML to Pydantic and JSON Schema generation."""

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


def test_parse_valid_yaml():
    """Test parsing valid YAML DSL."""
    yaml_content = """
flow:
  name: TestFlow
  version: "1.0"
  description: Test workflow

form:
  fields:
    - name: username
      type: text
      required: true

workflow:
  steps:
    - id: step1
      type: tool_call
      tool: http_request
"""
    dsl = parse_yaml(yaml_content)
    assert dsl["flow"]["name"] == "TestFlow"
    assert dsl["flow"]["version"] == "1.0"
    assert len(dsl["form"]["fields"]) == 1
    assert len(dsl["workflow"]["steps"]) == 1


def test_parse_yaml_missing_required_section():
    """Test that missing required sections raise ValueError."""
    yaml_missing_flow = """
form:
  fields:
    - name: test
      type: text
"""
    with pytest.raises(ValueError, match="Missing required section: flow"):
        parse_yaml(yaml_missing_flow)

    yaml_missing_form = """
flow:
  name: Test
workflow:
  steps: []
"""
    with pytest.raises(ValueError, match="Missing required section: form"):
        parse_yaml(yaml_missing_form)


def test_compile_form_model_text_field():
    """Test compiling text field with regex validation."""
    form_def = {
        "fields": [
            {
                "name": "username",
                "type": "text",
                "required": True,
                "regex": "^[a-z0-9_]+$",
                "description": "Username",
            }
        ]
    }

    model_cls, schema = compile_form_model(form_def)

    # Test valid instance
    instance = model_cls(username="test_user")
    assert cast(Any, instance).username == "test_user"

    # Test JSON schema contains pattern
    assert "properties" in schema
    assert "username" in schema["properties"]
    assert schema["properties"]["username"]["pattern"] == "^[a-z0-9_]+$"
    assert schema["properties"]["username"]["description"] == "Username"


def test_compile_form_model_number_field_with_constraints():
    """Test compiling number field with min/max validation."""
    form_def = {
        "fields": [{"name": "age", "type": "number", "required": True, "min": 18, "max": 120}]
    }

    model_cls, schema = compile_form_model(form_def)

    # Test valid instance
    instance = model_cls(age=25)
    assert cast(Any, instance).age == 25

    # Test min constraint
    with pytest.raises(ValidationError):
        model_cls(age=10)

    # Test max constraint
    with pytest.raises(ValidationError):
        model_cls(age=150)

    # Test JSON schema contains constraints
    assert schema["properties"]["age"]["minimum"] == 18
    assert schema["properties"]["age"]["maximum"] == 120


def test_compile_form_model_optional_fields():
    """Test optional fields with default None."""
    form_def = {
        "fields": [
            {"name": "email", "type": "text", "required": True},
            {"name": "phone", "type": "text", "required": False},
        ]
    }

    model_cls, schema = compile_form_model(form_def)

    # Test with only required field
    instance = model_cls(email="test@example.com")
    assert cast(Any, instance).email == "test@example.com"
    assert cast(Any, instance).phone is None

    # Test with both fields
    instance2 = model_cls(email="test@example.com", phone="123-456-7890")
    assert cast(Any, instance2).phone == "123-456-7890"

    # Verify required in schema
    assert "email" in schema.get("required", [])
    assert "phone" not in schema.get("required", [])


def test_compile_form_model_boolean_field():
    """Test boolean field compilation."""
    form_def = {"fields": [{"name": "newsletter", "type": "boolean", "required": True}]}

    model_cls, schema = compile_form_model(form_def)

    instance = model_cls(newsletter=True)
    assert cast(Any, instance).newsletter is True

    instance2 = model_cls(newsletter=False)
    assert cast(Any, instance2).newsletter is False

    assert schema["properties"]["newsletter"]["type"] == "boolean"


def test_compile_form_model_float_field():
    """Test float field with validation."""
    form_def = {
        "fields": [{"name": "price", "type": "float", "required": True, "min": 0.0, "max": 9999.99}]
    }

    model_cls, schema = compile_form_model(form_def)

    instance = model_cls(price=99.99)
    assert cast(Any, instance).price == 99.99

    # Test constraints
    with pytest.raises(ValidationError):
        model_cls(price=-1.0)


def test_compile_form_model_unknown_type_defaults_to_str():
    """Test unknown field types default to string."""
    form_def = {"fields": [{"name": "unknown_field", "type": "unknown_type", "required": True}]}

    model_cls, schema = compile_form_model(form_def)

    instance = model_cls(unknown_field="test")
    assert cast(Any, instance).unknown_field == "test"


def test_compile_workflow_spec():
    """Test workflow specification compilation."""
    workflow_def = {
        "steps": [{"id": "step1", "type": "tool_call"}, {"id": "step2", "type": "ai.assess"}]
    }

    spec = compile_workflow_spec(workflow_def, "TestFlow")

    assert spec["name"] == "TestFlow"
    assert len(spec["steps"]) == 2
    assert spec["steps"][0]["id"] == "step1"
    assert spec["steps"][1]["id"] == "step2"


def test_compile_policies_with_defaults():
    """Test policy compilation with default values."""
    policies = compile_policies(None)

    assert policies["budget"]["max_tokens"] == 100000
    assert policies["budget"]["max_cost_usd"] == 10.0
    assert policies["budget"]["max_steps"] == 50
    assert policies["rate_limits"]["max_requests_per_minute"] == 60
    assert policies["pii"]["enforce_redaction"] is True


def test_compile_policies_with_overrides():
    """Test policy compilation with custom values."""
    policies_def = {
        "budget": {"max_tokens": 50000, "max_cost_usd": 5.0},
        "pii": {"enforce_redaction": False},
    }

    policies = compile_policies(policies_def)

    assert policies["budget"]["max_tokens"] == 50000
    assert policies["budget"]["max_cost_usd"] == 5.0
    assert policies["budget"]["max_steps"] == 50  # Default
    assert policies["pii"]["enforce_redaction"] is False


def test_compile_dsl_full_integration():
    """Test full DSL compilation end-to-end."""
    yaml_content = """
flow:
  name: UserOnboarding
  version: "1.0"
  description: Onboard new users

form:
  fields:
    - name: email
      type: text
      required: true
      regex: "^[a-zA-Z0-9_]+@[a-zA-Z0-9]+[.][a-z]+$"
    - name: age
      type: number
      required: true
      min: 18
      max: 120

workflow:
  steps:
    - id: validate_email
      type: tool_call
      tool: http_request
      description: Validate email address
    - id: assess_risk
      type: ai.assess
      description: Assess user risk level

policies:
  budget:
    max_tokens: 50000
    max_cost_usd: 5.0
  pii:
    enforce_redaction: true

credentials:
  uses:
    - github_token
    - slack_webhook
"""

    compiled = compile_dsl(yaml_content)

    # Verify flow metadata
    assert compiled.flow_name == "UserOnboarding"
    assert compiled.flow_version == "1.0"
    assert compiled.flow_description == "Onboard new users"

    # Verify form model
    assert compiled.form_model is not None
    instance = compiled.form_model(email="test@example.com", age=25)
    assert cast(Any, instance).email == "test@example.com"
    assert cast(Any, instance).age == 25

    # Verify form schema
    assert "properties" in compiled.form_schema
    assert "email" in compiled.form_schema["properties"]
    assert "age" in compiled.form_schema["properties"]

    # Verify workflow spec
    assert compiled.workflow_spec["name"] == "UserOnboarding"
    assert len(compiled.workflow_spec["steps"]) == 2
    assert compiled.workflow_spec["steps"][0]["id"] == "validate_email"

    # Verify policies
    assert compiled.policies["budget"]["max_tokens"] == 50000
    assert compiled.policies["pii"]["enforce_redaction"] is True

    # Verify credentials
    assert len(compiled.credentials) == 2
    assert "github_token" in compiled.credentials


def test_compile_dsl_invalid_yaml_syntax():
    """Test compilation fails with invalid YAML."""
    invalid_yaml = """
flow:
  name: Test
  bad indent
"""
    with pytest.raises(ValueError, match="Invalid YAML syntax"):
        compile_dsl(invalid_yaml)


def test_form_model_invalid_regex():
    """Test that invalid regex patterns are caught."""
    form_def = {
        "fields": [{"name": "username", "type": "text", "required": True, "regex": "^[a-z]+$"}]
    }

    model_cls, _ = compile_form_model(form_def)

    # Valid pattern
    model_cls(username="abc")

    # Invalid pattern
    with pytest.raises(ValidationError):
        model_cls(username="ABC123")
