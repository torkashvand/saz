"""Executor Agent - Grounds plans into concrete tool calls with variable substitution."""

from collections.abc import Callable
from typing import Any

import structlog

from saz.engine.templating import resolve_template

from .schemas import PlanStep, ToolCall

logger = structlog.get_logger(__name__)


class ExecutorAgent:
    """Grounds plan steps into executable tool calls"""

    def __init__(self, secret_resolver: Callable[[str], str | None] | None = None):
        self.logger = logger.bind(agent="executor")
        self.secret_resolver = secret_resolver

    def ground(
        self,
        step: PlanStep,
        tool_registry: dict[str, dict],
        current_data: dict[str, Any],
        run_id: str,
    ) -> ToolCall:
        """
        Ground a plan step into a concrete tool call.

        Args:
            step: PlanStep from execution plan
            tool_registry: Available tools (indexed by name)
            current_data: Current workflow state for variable substitution
            run_id: Current run identifier for idempotency key

        Returns:
            ToolCall with concrete arguments ready for execution

        Raises:
            ValueError: If tool not found or arguments invalid
        """
        self.logger.info(
            "grounding_step",
            step_id=step.step_id,
            tool_name=step.tool_name,
            step_type=step.step_type,
        )

        # Validate tool exists
        if step.tool_name not in tool_registry:
            raise ValueError(f"Tool '{step.tool_name}' not found in registry")

        tool_spec = tool_registry[step.tool_name]

        grounded_args = resolve_template(
            step.input_template,
            form_data=current_data.get('form_data', {}),
            step_results=current_data.get('step_results', {}),
            secret_resolver=self.secret_resolver,
        )

        # Validate against tool schema (basic check)
        self._validate_arguments(grounded_args, tool_spec)

        # Generate idempotency key
        idempotency_key = f"{run_id}:{step.step_id}"

        # Build rationale
        rationale = (
            f"Executing {step.tool_name} for step {step.step_id}. Reasoning: {step.reasoning}"
        )

        tool_call = ToolCall(
            tool=step.tool_name,
            arguments=grounded_args,
            idempotency_key=idempotency_key,
            rationale=rationale,
        )

        self.logger.info(
            "step_grounded",
            step_id=step.step_id,
            tool=tool_call.tool,
            idempotency_key=tool_call.idempotency_key,
        )

        return tool_call

    def _validate_arguments(self, arguments: dict[str, Any], tool_spec: dict[str, Any]) -> None:
        """
        Validate grounded arguments against the tool's input schema.

        Checks required-field presence, enum membership, and unresolved
        template strings. Tool specs in this repo are not consistent about
        key casing — HttpTool/WebhookTool/ArtifactTool emit ``inputSchema``
        (camelCase) while the AI-op spec factory and AnsibleTool emit
        ``input_schema`` (snake_case). Look at both so validation fires for
        every registered tool.

        Args:
            arguments: Grounded arguments
            tool_spec: Tool specification with inputSchema/input_schema

        Raises:
            ValueError: If required parameters are missing, an enum value is
                invalid, or a template reference was left unresolved.
        """
        name = tool_spec["name"]
        input_schema = tool_spec.get("input_schema") or tool_spec.get("inputSchema") or {}
        required_params = input_schema.get("required", [])

        missing = [p for p in required_params if p not in arguments]
        if missing:
            raise ValueError(f"Missing required parameters for {name}: {missing}")

        properties = input_schema.get("properties", {})
        for key, value in arguments.items():
            # An unresolved template that survived grounding means a bad
            # $form/$step/$env reference — fail before the tool executes.
            if isinstance(value, str) and "{{" in value and "}}" in value:
                raise ValueError(
                    f"Unresolved template reference in argument '{key}' for {name}: {value!r}"
                )
            prop = properties.get(key)
            if isinstance(prop, dict) and "enum" in prop and value not in prop["enum"]:
                raise ValueError(
                    f"Invalid value for '{key}' in {name}: {value!r} not in {prop['enum']}"
                )

        self.logger.debug("arguments_validated", tool=name, required_params=required_params)
