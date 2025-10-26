"""Deterministic expression engine for template resolution.

Supports:
- {{ $form.field_name }}
- {{ $step('step_id').output_field }}
- {{ $secret('credential_name') }}
- {{ $env('VAR_NAME') }}
- Helpers: coalesce(a, b, default), toInt(x), lower(x), upper(x), len(x)

Pure functions, no LLM calls.
"""
import re
import os
from typing import Any, Dict, Callable
import structlog

logger = structlog.get_logger(__name__)


class ExpressionEngine:
    """Deterministic expression resolver for workflow templates."""

    def __init__(
        self,
        form_data: Dict[str, Any],
        step_outputs: Dict[str, Any],
        secrets_resolver: Callable[[str], str] | None = None,
        env_resolver: Callable[[str], str] | None = None
    ):
        """
        Initialize expression engine.

        Args:
            form_data: Form submission data
            step_outputs: Map of step_id -> output data
            secrets_resolver: Function to resolve secret by name (injected)
            env_resolver: Function to resolve env var by name (default: os.getenv)
        """
        self.form_data = form_data
        self.step_outputs = step_outputs
        self.secrets_resolver = secrets_resolver or (lambda name: "")
        self.env_resolver = env_resolver or os.getenv

        # Register helper functions
        self.helpers = {
            "coalesce": self._coalesce,
            "toInt": self._to_int,
            "lower": self._lower,
            "upper": self._upper,
            "len": self._len,
            "toString": self._to_string,
            "toBool": self._to_bool,
        }

    def resolve(self, value: Any) -> Any:
        """
        Recursively resolve expressions in a value.

        Args:
            value: Value that may contain template expressions

        Returns:
            Resolved value
        """
        if isinstance(value, str):
            return self._resolve_string(value)
        elif isinstance(value, dict):
            return {k: self.resolve(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self.resolve(item) for item in value]
        else:
            return value

    def _resolve_string(self, template: str) -> Any:
        """
        Resolve template string with expressions.

        Examples:
            "Hello {{ $form.username }}" -> "Hello john"
            "{{ $step('validate').status }}" -> "success"
            "{{ coalesce($form.email, 'default@example.com') }}" -> "user@example.com"
        """
        # Pattern: {{ ... }}
        pattern = r'\{\{\s*([^}]+)\s*\}\}'

        def replacer(match):
            expr = match.group(1).strip()
            try:
                result = self._eval_expression(expr)
                return str(result) if result is not None else ""
            except Exception as e:
                logger.warning("expression_eval_failed", expr=expr, error=str(e))
                return match.group(0)  # Return original if eval fails

        # Check if entire string is a single expression (return typed value)
        single_expr_match = re.fullmatch(pattern, template)
        if single_expr_match:
            expr = single_expr_match.group(1).strip()
            return self._eval_expression(expr)

        # Multiple expressions or mixed text (return string)
        return re.sub(pattern, replacer, template)

    def _eval_expression(self, expr: str) -> Any:
        """
        Evaluate a single expression.

        Supported:
            $form.field_name
            $step('step_id').field
            $secret('name')
            $env('VAR')
            helper(args...)
        """
        expr = expr.strip()

        # $form.field_name
        if expr.startswith("$form."):
            field = expr[6:]
            return self._get_nested(self.form_data, field)

        # $step('step_id').field or $step('step_id')
        step_match = re.match(r"\$step\('([^']+)'\)(?:\.(.+))?", expr)
        if step_match:
            step_id = step_match.group(1)
            field = step_match.group(2)
            step_data = self.step_outputs.get(step_id, {})
            if field:
                return self._get_nested(step_data, field)
            return step_data

        # $secret('name')
        secret_match = re.match(r"\$secret\('([^']+)'\)", expr)
        if secret_match:
            secret_name = secret_match.group(1)
            return self.secrets_resolver(secret_name)

        # $env('VAR_NAME')
        env_match = re.match(r"\$env\('([^']+)'\)", expr)
        if env_match:
            var_name = env_match.group(1)
            return self.env_resolver(var_name) or ""

        # Helper functions
        helper_match = re.match(r"(\w+)\((.*)\)", expr)
        if helper_match:
            helper_name = helper_match.group(1)
            args_str = helper_match.group(2)
            if helper_name in self.helpers:
                args = self._parse_args(args_str)
                return self.helpers[helper_name](*args)

        # Literal values
        if expr.startswith("'") and expr.endswith("'"):
            return expr[1:-1]
        if expr.startswith('"') and expr.endswith('"'):
            return expr[1:-1]
        if expr.isdigit():
            return int(expr)
        if expr in ("true", "True"):
            return True
        if expr in ("false", "False"):
            return False
        if expr == "null":
            return None

        # Return as-is if unrecognized
        return expr

    def _get_nested(self, data: Dict[str, Any], path: str) -> Any:
        """Get nested field from dict using dot notation."""
        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    def _parse_args(self, args_str: str) -> list:
        """Parse comma-separated arguments (simple parser)."""
        if not args_str.strip():
            return []

        # Simple split by comma (doesn't handle nested parens)
        raw_args = [arg.strip() for arg in args_str.split(",")]
        return [self._eval_expression(arg) for arg in raw_args]

    # --- Helper Functions ---

    def _coalesce(self, *args) -> Any:
        """Return first non-null value."""
        for arg in args:
            if arg is not None:
                return arg
        return None

    def _to_int(self, value: Any) -> int:
        """Convert to integer."""
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0

    def _lower(self, value: Any) -> str:
        """Convert to lowercase."""
        return str(value).lower()

    def _upper(self, value: Any) -> str:
        """Convert to uppercase."""
        return str(value).upper()

    def _len(self, value: Any) -> int:
        """Get length of string/list/dict."""
        try:
            return len(value)
        except TypeError:
            return 0

    def _to_string(self, value: Any) -> str:
        """Convert to string."""
        return str(value)

    def _to_bool(self, value: Any) -> bool:
        """Convert to boolean."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)


def resolve_expressions(
    template: Any,
    form_data: Dict[str, Any],
    step_outputs: Dict[str, Any],
    secrets_resolver: Callable[[str], str] | None = None
) -> Any:
    """
    Convenience function to resolve expressions in a template.

    Args:
        template: Template value (string, dict, list, etc.)
        form_data: Form submission data
        step_outputs: Map of step_id -> output data
        secrets_resolver: Function to resolve secrets

    Returns:
        Resolved value
    """
    engine = ExpressionEngine(
        form_data=form_data,
        step_outputs=step_outputs,
        secrets_resolver=secrets_resolver
    )
    return engine.resolve(template)
