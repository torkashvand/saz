"""YAML → Agentic Workflow Compiler.

Takes YAML form/workflow definitions and generates:
1. Pydantic v2 model for the form
2. JSON schema for UI rendering
3. Agentic workflow specification (tool calls, AI branches, human gates)
"""

from typing import Any, cast

import yaml
from pydantic import BaseModel, Field, create_model


class CompiledFlow:
    """Result of compiling a form+workflow YAML."""

    def __init__(
        self,
        name: str,
        form_model: type[BaseModel],
        workflow_spec: dict,
        form_yaml: dict,
        workflow_yaml: dict | None,
        budget: dict | None = None,
    ):
        self.name = name
        self.form_model = form_model
        self.workflow_spec = workflow_spec
        self.form_yaml = form_yaml
        self.workflow_yaml = workflow_yaml
        self.budget = budget or {
            "max_tokens": 100000,
            "max_cost_usd": 10.0,
            "max_steps": 50,
            "max_time_seconds": 3600,
        }

    @property
    def json_schema(self) -> dict[str, Any]:
        """Generate JSON schema for form (for UI rendering)."""
        return self.form_model.model_json_schema()


def parse_yaml_form(form_yaml: dict) -> type[BaseModel]:
    """Convert YAML form definition to Pydantic v2 model.

    YAML format:
        name: my_form
        fields:
          - name: username
            type: text
            required: true
            regex: "^[a-z]+$"
          - name: age
            type: number
            required: false
            min: 0
            max: 120
          - name: enabled
            type: boolean
            required: true
    """
    form_name = form_yaml.get("name", "DynamicForm")
    fields_def = form_yaml.get("fields", [])

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
    model_cls = create_model(form_name, **pydantic_fields)  # type: ignore[call-overload]
    return cast(type[BaseModel], model_cls)


def create_agentic_workflow_spec(
    workflow_yaml: dict | None,
    form_name: str,
) -> dict:
    """Create agentic workflow specification from YAML.

    Agentic workflow YAML:
        name: customer_onboarding
        description: Onboard new customer with AI-powered validation
        budget:
          max_tokens: 50000
          max_cost_usd: 5.0
          max_steps: 20
        steps:
          - id: collect_form
            type: human_input
            description: Collect customer information

          - id: validate_data
            type: tool_call
            tool: http_request
            description: Validate customer data with external API
            input:
              method: POST
              url: "{{validation_api_url}}"
              body:
                email: "{{email}}"
                company: "{{company}}"

          - id: check_risk
            type: ai_branch
            description: Assess risk and decide next action
            condition: "Is this a high-risk customer based on validation result?"
            branches:
              high_risk:
                - id: escalate_to_human
                  type: human_approval
                  description: High-risk customer requires manual approval
              low_risk:
                - id: auto_approve
                  type: tool_call
                  tool: artifact_store
                  description: Store approval artifact

          - id: send_welcome_email
            type: tool_call
            tool: http_request
            description: Send welcome email
            input:
              method: POST
              url: "{{email_api_url}}"
              body:
                to: "{{email}}"
                template: "welcome"
    """
    if not workflow_yaml:
        # Default simple workflow
        return {
            "name": f"default_{form_name}",
            "description": f"Default workflow for {form_name}",
            "steps": [
                {
                    "id": "collect_form",
                    "type": "human_input",
                    "description": "Collect form data from user",
                },
                {
                    "id": "store_result",
                    "type": "tool_call",
                    "tool": "artifact_store",
                    "description": "Store final result",
                    "input": {"name": "form_submission", "content": "{{$all}}"},
                },
            ],
        }

    # Parse custom agentic workflow
    return {
        "name": workflow_yaml.get("name", form_name),
        "description": workflow_yaml.get("description", ""),
        "steps": workflow_yaml.get("steps", []),
        "budget": workflow_yaml.get("budget", {}),
    }


def compile_form_and_workflow(
    form_yaml_str: str, workflow_yaml_str: str | None = None
) -> CompiledFlow:
    """Compile YAML form (and optional workflow) into Pydantic model + Agentic Workflow Spec.

    Args:
        form_yaml_str: YAML string defining the form
        workflow_yaml_str: Optional YAML string defining agentic workflow

    Returns:
        CompiledFlow with form model, workflow spec, and JSON schema
    """
    # Parse YAMLs
    form_yaml = yaml.safe_load(form_yaml_str)
    workflow_yaml = yaml.safe_load(workflow_yaml_str) if workflow_yaml_str else None

    # Generate Pydantic model
    form_model = parse_yaml_form(form_yaml)
    form_name = form_yaml.get("name", "DynamicForm")

    # Generate agentic workflow spec
    workflow_spec = create_agentic_workflow_spec(workflow_yaml, form_name)

    # Extract budget if specified
    budget = workflow_yaml.get("budget") if workflow_yaml else None

    return CompiledFlow(
        name=form_name,
        form_model=form_model,
        workflow_spec=workflow_spec,
        form_yaml=form_yaml,
        workflow_yaml=workflow_yaml,
        budget=budget,
    )
