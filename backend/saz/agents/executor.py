"""Executor Agent - Grounds plans into concrete tool calls with variable substitution."""

import re
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

    def _substitute_variables(
        self, template: dict[str, Any], data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Recursively substitute {{variable}} placeholders with actual values.

        Args:
            template: Input template with {{variable}} placeholders
            data: Available data for substitution

        Returns:
            Template with variables substituted

        Raises:
            ValueError: If referenced variable not found
        """
        if isinstance(template, dict):
            return {key: self._substitute_variables(value, data) for key, value in template.items()}
        elif isinstance(template, list):
            return [self._substitute_variables(item, data) for item in template]
        elif isinstance(template, str):
            # Match {{variable}} or {{nested.variable}}
            pattern = r'\{\{([^}]+)\}\}'
            matches = re.findall(pattern, template)

            if not matches:
                return template

            # If entire string is a variable, return the value directly (preserving type)
            if len(matches) == 1 and template == f"{{{{{matches[0]}}}}}":
                var_path = matches[0].strip()
                return self._get_nested_value(data, var_path)

            # Otherwise, do string substitution
            result = template
            for match in matches:
                var_path = match.strip()
                value = self._get_nested_value(data, var_path)
                result = result.replace(f"{{{{{match}}}}}", str(value))

            return result
        else:
            return template

    def _get_nested_value(self, data: dict, path: str) -> Any:
        """
        Get value from nested dictionary using dot notation.

        Args:
            data: Dictionary to query
            path: Dot-separated path (e.g., "user.email")

        Returns:
            Value at path

        Raises:
            ValueError: If path not found
        """
        keys = path.split('.')
        value = data

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                raise ValueError(f"Variable path '{path}' not found in data")

        return value

    def _validate_arguments(self, arguments: dict[str, Any], tool_spec: dict[str, Any]) -> None:
        """
        Basic validation that required parameters are present.

        Tool specs in this repo are not consistent about key casing —
        HttpTool/WebhookTool/ArtifactTool emit ``inputSchema`` (camelCase)
        while the AI-op spec factory and AnsibleTool emit ``input_schema``
        (snake_case). Look at both so the required-field check actually
        fires for every registered tool.

        Args:
            arguments: Grounded arguments
            tool_spec: Tool specification with inputSchema/input_schema

        Raises:
            ValueError: If required parameters missing
        """
        input_schema = tool_spec.get('input_schema') or tool_spec.get('inputSchema') or {}
        required_params = input_schema.get('required', [])

        missing = [p for p in required_params if p not in arguments]
        if missing:
            raise ValueError(f"Missing required parameters for {tool_spec['name']}: {missing}")

        self.logger.debug(
            "arguments_validated", tool=tool_spec['name'], required_params=required_params
        )
