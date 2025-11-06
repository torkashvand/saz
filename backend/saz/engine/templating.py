"""Templating engine for Saz workflows.

Supports:
- {{ $form.field }} - Access form payload (native types)
- {{ $step('step_id').prop }} - Access prior step results
- {{ $env('VAR_NAME') }} - Read environment variable
- {{ $secret('SECRET_NAME') }} - Retrieve credential (requires vault)

Native type support: If template is the entire string value, return the native type.
Otherwise, perform string interpolation.
"""

import json
import os
import re
from collections.abc import Callable
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class TemplateContext:
    """Context for template resolution."""

    def __init__(
        self,
        form_data: dict[str, Any],
        step_results: dict[str, Any],
        secret_resolver: Callable[[str], str | None] | None = None,
    ):
        """
        Initialize template context.

        Args:
            form_data: Initial form payload
            step_results: Dictionary of step_id -> result
            secret_resolver: Function to resolve secrets (step_id, secret_name) -> value
        """
        self.form_data = form_data
        self.step_results = step_results
        self.secret_resolver: Callable[[str], str | None] = secret_resolver or (lambda name: None)
        self.logger = logger.bind(component="templating")

    def resolve(self, template: Any) -> Any:
        """
        Resolve a template value.

        Args:
            template: Value to resolve (str, dict, list, or primitive)

        Returns:
            Resolved value with native types
        """
        if isinstance(template, str):
            return self._resolve_string(template)
        elif isinstance(template, dict):
            return {key: self.resolve(value) for key, value in template.items()}
        elif isinstance(template, list):
            return [self.resolve(item) for item in template]
        else:
            # Primitive value, return as-is
            return template

    def _resolve_string(self, template: str) -> Any:
        """
        Resolve a string template.

        If the entire string is a single template expression, return native type.
        Otherwise, perform string interpolation.

        Args:
            template: Template string

        Returns:
            Resolved value (native type or interpolated string)
        """
        # Check if entire string is a single template expression
        single_expr = re.match(r'^\{\{\s*(.+?)\s*\}\}$', template)
        if single_expr:
            # Entire string is a template - return native type
            expr = single_expr.group(1)
            return self._evaluate_expression(expr)

        # Multiple expressions or mixed content - string interpolation
        def replacer(match: Any) -> str:
            expr = match.group(1).strip()
            value = self._evaluate_expression(expr)
            # Convert to string for interpolation
            if value is None:
                return ""
            elif isinstance(value, dict | list):
                return json.dumps(value)
            else:
                return str(value)

        pattern = r'\{\{\s*(.+?)\s*\}\}'
        result = re.sub(pattern, replacer, template)
        return result

    def _evaluate_expression(self, expr: str) -> Any:
        """
        Evaluate a template expression.

        Supports:
        - $form.field
        - $step('step_id').prop
        - $env('VAR_NAME')
        - $secret('SECRET_NAME')

        Args:
            expr: Expression string (without {{ }})

        Returns:
            Evaluated value
        """
        expr = expr.strip()

        # $form.field
        if expr.startswith('$form.'):
            field_name = expr[6:]  # Remove "$form."
            return self._resolve_form_field(field_name)

        # $step('step_id').prop or $step('step_id')
        step_match = re.match(r"\$step\(['\"](.+?)['\"]\)(?:\.(.+))?", expr)
        if step_match:
            step_id = step_match.group(1)
            prop_path = step_match.group(2)
            return self._resolve_step_result(step_id, prop_path)

        # $env('VAR_NAME')
        env_match = re.match(r"\$env\(['\"](.+?)['\"]\)", expr)
        if env_match:
            var_name = env_match.group(1)
            return self._resolve_env(var_name)

        # $secret('SECRET_NAME')
        secret_match = re.match(r"\$secret\(['\"](.+?)['\"]\)", expr)
        if secret_match:
            secret_name = secret_match.group(1)
            return self._resolve_secret(secret_name)

        self.logger.warning("unresolved_expression", expr=expr)
        return f"{{{{ {expr} }}}}"  # Return as-is if unresolved

    def _resolve_form_field(self, field_path: str) -> Any:
        """
        Resolve $form.field expression.

        Args:
            field_path: Field path (e.g., "username" or "user.name")

        Returns:
            Field value from form data
        """
        # Support nested paths with dot notation
        parts = field_path.split('.')
        value = self.form_data
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                self.logger.warning(
                    "form_field_not_found",
                    field_path=field_path,
                    available_fields=list(self.form_data.keys()),
                )
                return None
        return value

    def _resolve_step_result(self, step_id: str, prop_path: str | None) -> Any:
        """
        Resolve $step('step_id').prop expression.

        Args:
            step_id: Step identifier
            prop_path: Optional property path (e.g., "output.value")

        Returns:
            Step result or property value
        """
        # Look for step result with key pattern: step_id_result or step_id
        step_result = None
        if f"{step_id}_result" in self.step_results:
            step_result = self.step_results[f"{step_id}_result"]
        elif step_id in self.step_results:
            step_result = self.step_results[step_id]
        else:
            self.logger.warning(
                "step_result_not_found",
                step_id=step_id,
                available_steps=list(self.step_results.keys()),
            )
            return None

        # If no property path, return entire result
        if not prop_path:
            return step_result

        # Navigate property path
        parts = prop_path.split('.')
        value = step_result
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                self.logger.warning("step_property_not_found", step_id=step_id, prop_path=prop_path)
                return None
        return value

    def _resolve_env(self, var_name: str) -> str | None:
        """
        Resolve $env('VAR_NAME') expression.

        Args:
            var_name: Environment variable name

        Returns:
            Environment variable value or None
        """
        value = os.getenv(var_name)
        if value is None:
            self.logger.warning("env_var_not_found", var_name=var_name)
        return value

    def _resolve_secret(self, secret_name: str) -> str | None:
        """
        Resolve $secret('SECRET_NAME') expression.

        Args:
            secret_name: Secret/credential name

        Returns:
            Secret value or None

        Raises:
            ValueError: If secret not found and required
        """
        value = self.secret_resolver(secret_name)
        if value is None:
            error_msg = f"Secret '{secret_name}' not found. Please configure credential."
            self.logger.error("secret_not_found", secret_name=secret_name)
            raise ValueError(error_msg)
        return value


def resolve_template(
    template: Any,
    form_data: dict[str, Any],
    step_results: dict[str, Any],
    secret_resolver: Callable[[str], str | None] | None = None,
) -> Any:
    """
    Convenience function to resolve a template.

    Args:
        template: Template value to resolve
        form_data: Form payload
        step_results: Step results dictionary
        secret_resolver: Function to resolve secrets

    Returns:
        Resolved value
    """
    context = TemplateContext(form_data, step_results, secret_resolver)
    return context.resolve(template)
