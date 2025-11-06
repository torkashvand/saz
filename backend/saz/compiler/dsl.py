"""YAML DSL Compiler for Saz.

Parses single-file YAML with sections:
- flow: metadata (name, version, description)
- form: fields with validation
- triggers: manual, webhook, schedule
- workflow: steps (tool calls, AI ops, conditionals, approvals)
- policies: budget, rate_limits, pii
- credentials: uses list

Produces:
- Pydantic form model
- JSON Schema for UI
- Workflow specification for rule planner
- Policy configuration
"""

from typing import Any, cast

import structlog
import yaml
from pydantic import BaseModel, Field, create_model

logger = structlog.get_logger(__name__)


class DSLCompiled:
    """Result of compiling a DSL YAML."""

    def __init__(
        self,
        flow_name: str,
        flow_version: str | None,
        flow_description: str | None,
        form_model: type[BaseModel],
        form_schema: dict,
        workflow_spec: dict,
        triggers: dict,
        policies: dict,
        credentials: list[str],
        raw_dsl: dict,
    ):
        self.flow_name = flow_name
        self.flow_version = flow_version
        self.flow_description = flow_description
        self.form_model = form_model
        self.form_schema = form_schema
        self.workflow_spec = workflow_spec
        self.triggers = triggers
        self.policies = policies
        self.credentials = credentials
        self.raw_dsl = raw_dsl

    @property
    def json_schema(self) -> dict[str, Any]:
        """Generate JSON schema for form (for UI rendering)."""
        return self.form_schema


def parse_yaml(yaml_content: str) -> dict:
    """Parse YAML and validate structure.

    Args:
        yaml_content: YAML string content

    Returns:
        Parsed YAML dict

    Raises:
        ValueError: If YAML is invalid or missing required sections
    """
    try:
        dsl = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML syntax: {e}") from None

    if not isinstance(dsl, dict):
        raise ValueError("YAML root must be a dictionary")

    # Validate required sections
    if "flow" not in dsl:
        raise ValueError("Missing required section: flow")
    if "name" not in dsl["flow"]:
        raise ValueError("flow.name is required")

    # Form section is optional
    if "form" in dsl and "fields" not in dsl["form"]:
        raise ValueError("form.fields is required when form section is present")

    if "workflow" not in dsl:
        raise ValueError("Missing required section: workflow")
    if "steps" not in dsl["workflow"]:
        raise ValueError("workflow.steps is required")

    fields_count = len(dsl.get("form", {}).get("fields", []))
    logger.info(
        "dsl_parsed",
        flow_name=dsl["flow"]["name"],
        fields_count=fields_count,
        steps_count=len(dsl["workflow"]["steps"]),
    )

    return dsl


def compile_form_model(form_def: dict) -> tuple[type[BaseModel], dict]:
    """Compile form definition to Pydantic model and JSON Schema.

    Args:
        form_def: Form section from YAML

    Returns:
        Tuple of (Pydantic model class, JSON Schema dict)
    """
    fields_def = form_def.get("fields", [])

    # Build Pydantic field definitions
    pydantic_fields = {}
    for field_def in fields_def:
        field_name = field_def["name"]
        field_type_str = field_def.get("type", "text")
        is_required = field_def.get("required", True)

        # Map YAML types to Python types
        type_map = {
            "text": str,
            "number": int,
            "float": float,
            "boolean": bool,
        }
        base_type = type_map.get(field_type_str, str)

        # Build Field kwargs for validation
        field_kwargs: dict[str, Any] = {}
        if not is_required:
            field_kwargs["default"] = None

        if "regex" in field_def and isinstance(base_type, type) and base_type is str:
            field_kwargs["pattern"] = field_def["regex"]
        if "min" in field_def and base_type in (int, float):
            field_kwargs["ge"] = field_def["min"]
        if "max" in field_def and base_type in (int, float):
            field_kwargs["le"] = field_def["max"]
        if "description" in field_def:
            field_kwargs["description"] = field_def["description"]

        # Create field
        if is_required:
            pydantic_fields[field_name] = (
                base_type,
                Field(**field_kwargs) if field_kwargs else ...,
            )
        else:
            # Mypy can't infer union types in tuples - cast to satisfy type checker
            pydantic_fields[field_name] = cast(Any, (base_type | None, Field(**field_kwargs)))

    # Create dynamic Pydantic model - cast needed for dynamic field definitions
    model_cls = create_model("DynamicForm", **pydantic_fields)  # type: ignore[call-overload]

    # Generate JSON Schema
    json_schema = model_cls.model_json_schema()

    return cast(type[BaseModel], model_cls), json_schema


def compile_workflow_spec(workflow_def: dict, flow_name: str) -> dict:
    """Compile workflow definition to execution spec.

    Args:
        workflow_def: Workflow section from YAML
        flow_name: Flow name for default workflow name

    Returns:
        Workflow specification dict
    """
    return {
        "name": flow_name,
        "steps": workflow_def.get("steps", []),
    }


def compile_policies(policies_def: dict | None) -> dict:
    """Compile policies section with defaults.

    Args:
        policies_def: Policies section from YAML

    Returns:
        Policy configuration dict
    """
    if not policies_def:
        return {
            "budget": {
                "max_tokens": 100000,
                "max_cost_usd": 10.0,
                "max_steps": 50,
                "max_time_seconds": 3600,
            },
            "rate_limits": {"max_requests_per_minute": 60},
            "pii": {"enforce_redaction": True, "allowed_fields": []},
        }

    # Merge with defaults
    budget = policies_def.get("budget", {})
    rate_limits = policies_def.get("rate_limits", {})
    pii = policies_def.get("pii", {})

    return {
        "budget": {
            "max_tokens": budget.get("max_tokens", 100000),
            "max_cost_usd": budget.get("max_cost_usd", 10.0),
            "max_steps": budget.get("max_steps", 50),
            "max_time_seconds": budget.get("max_time_seconds", 3600),
        },
        "rate_limits": {"max_requests_per_minute": rate_limits.get("max_requests_per_minute", 60)},
        "pii": {
            "enforce_redaction": pii.get("enforce_redaction", True),
            "allowed_fields": pii.get("allowed_fields", []),
        },
    }


def compile_dsl(yaml_content: str) -> DSLCompiled:
    """Compile YAML DSL to executable components.

    Args:
        yaml_content: YAML string

    Returns:
        DSLCompiled object with all compiled components

    Raises:
        ValueError: If YAML is invalid
    """
    # Parse and validate
    dsl = parse_yaml(yaml_content)

    # Extract sections
    flow = dsl["flow"]
    form = dsl.get("form", {"fields": []})
    workflow = dsl["workflow"]
    triggers = dsl.get("triggers", {"manual": True})
    policies = dsl.get("policies")
    credentials = dsl.get("credentials", {}).get("uses", [])

    # Compile components
    form_model, form_schema = compile_form_model(form)
    workflow_spec = compile_workflow_spec(workflow, flow["name"])
    policy_config = compile_policies(policies)

    logger.info(
        "dsl_compiled",
        flow_name=flow["name"],
        form_fields=len(form.get("fields", [])),
        workflow_steps=len(workflow["steps"]),
        credentials=len(credentials),
    )

    return DSLCompiled(
        flow_name=flow["name"],
        flow_version=flow.get("version"),
        flow_description=flow.get("description"),
        form_model=form_model,
        form_schema=form_schema,
        workflow_spec=workflow_spec,
        triggers=triggers,
        policies=policy_config,
        credentials=credentials,
        raw_dsl=dsl,
    )
