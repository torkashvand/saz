"""Template expression validator for DSL compiler."""

import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Template expression patterns
_TEMPLATE_RE = re.compile(r'\{\{\s*(.+?)\s*\}\}')
_STEP_RE = re.compile(r"\$step\(['\"](.+?)['\"]\)(?:\.(.+))?")
_FORM_RE = re.compile(r"\$form\.(.+)")
_ENV_RE = re.compile(r"\$env\(['\"](.+?)['\"]\)")
_SECRET_RE = re.compile(r"\$secret\(['\"](.+?)['\"]\)")


class TemplateValidationError(Exception):
    """Raised when template syntax is invalid."""

    pass


class TemplateValidator:
    """Validates template expressions in workflow DSL."""

    def __init__(self):
        self.logger = logger.bind(component="template_validator")
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def validate_workflow(
        self,
        workflow_spec: dict[str, Any],
        form_fields: list[str],
        step_ids: list[str],
    ) -> tuple[list[str], list[str]]:
        """
        Validate all template expressions in a workflow.

        Args:
            workflow_spec: Workflow specification
            form_fields: List of valid form field names
            step_ids: List of valid step IDs

        Returns:
            Tuple of (warnings, errors)
        """
        self.warnings = []
        self.errors = []

        # Extract and validate all templates
        self._validate_object(workflow_spec, form_fields, set(step_ids))

        return self.warnings, self.errors

    def _validate_object(
        self, obj: Any, form_fields: list[str], step_ids: set[str], path: str = ""
    ) -> None:
        """Recursively validate templates in any object."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                self._validate_object(
                    value, form_fields, step_ids, f"{path}.{key}" if path else key
                )
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                self._validate_object(item, form_fields, step_ids, f"{path}[{idx}]")
        elif isinstance(obj, str):
            self._validate_string_templates(obj, form_fields, step_ids, path)

    def _validate_string_templates(
        self, text: str, form_fields: list[str], step_ids: set[str], path: str
    ) -> None:
        """Validate all template expressions in a string."""
        for match in _TEMPLATE_RE.finditer(text):
            expr = match.group(1).strip()
            self._validate_expression(expr, form_fields, step_ids, path)

    def _validate_expression(
        self, expr: str, form_fields: list[str], step_ids: set[str], path: str
    ) -> None:
        """Validate a single template expression."""

        # Check for $step() expressions
        step_match = _STEP_RE.match(expr)
        if step_match:
            step_id = step_match.group(1)
            prop_path = step_match.group(2) or ""

            # Validate step ID exists
            if step_id not in step_ids:
                self.errors.append(
                    f"At {path}: Unknown step ID '{step_id}' in template. "
                    f"Available steps: {sorted(step_ids)}"
                )

            # Check for common mistake: .output.field instead of .field
            if prop_path:
                if ".output." in prop_path or prop_path.startswith("output."):
                    fixed_path = prop_path.replace("output.", "", 1)
                    self.errors.append(
                        f"At {path}: Invalid template syntax "
                        f"'{{{{ $step('{step_id}').{prop_path} }}}}'. "
                        f"Step references automatically access the 'output' key. "
                        f"Use '{{{{ $step('{step_id}').{fixed_path} }}}}' instead."
                    )
                elif prop_path == "output":
                    self.warnings.append(
                        f"At {path}: Unnecessary '.output' in template "
                        f"'{{{{ $step('{step_id}').output }}}}'. "
                        f"Use '{{{{ $step('{step_id}') }}}}' instead (output is implicit)."
                    )

            return

        # Check for $form expressions
        form_match = _FORM_RE.match(expr)
        if form_match:
            field_path = form_match.group(1)
            field_name = field_path.split(".")[0]

            # Validate field exists
            if field_name not in form_fields:
                self.warnings.append(
                    f"At {path}: Unknown form field '{field_name}' in template. "
                    f"Available fields: {form_fields}"
                )

            return

        # Check for $env() expressions
        env_match = _ENV_RE.match(expr)
        if env_match:
            # Can't validate env vars at compile time, that's OK
            return

        # Check for $secret() expressions
        secret_match = _SECRET_RE.match(expr)
        if secret_match:
            # Secret validation happens at runtime via credentials check
            return

        # Unknown expression pattern
        if expr.startswith("$"):
            self.warnings.append(f"At {path}: Unrecognized template expression '{{{{ {expr} }}}}'")


def validate_templates(
    workflow_spec: dict[str, Any],
    form_fields: list[str],
    step_ids: list[str],
) -> tuple[list[str], list[str]]:
    """
    Validate template expressions in workflow.

    Args:
        workflow_spec: Workflow specification
        form_fields: Valid form field names
        step_ids: Valid step IDs

    Returns:
        Tuple of (warnings, errors)
    """
    validator = TemplateValidator()
    return validator.validate_workflow(workflow_spec, form_fields, step_ids)
