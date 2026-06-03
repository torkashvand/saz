"""Template expression validator for DSL compiler."""

import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Template expression patterns.
#
# A single ``{{ ... }}`` block can hold a compound expression with several
# references (e.g. a condition: ``$form.a > 0 && $step('x').y == "z"``). The
# reference patterns therefore match an IDENTIFIER/PATH only — not "the rest of
# the line" — and the validator scans each block with ``finditer`` so every
# reference is checked and a multi-clause condition does not produce spurious
# "Unknown form field" warnings from a greedy ``.+`` capture.
_TEMPLATE_RE = re.compile(r'\{\{\s*(.+?)\s*\}\}')
_STEP_RE = re.compile(r"\$step\(['\"](.+?)['\"]\)(?:\.([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*))?")
_FORM_RE = re.compile(r"\$form\.([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)")
_ENV_RE = re.compile(r"\$env\(['\"](.+?)['\"](?:\s*,\s*['\"](.*?)['\"])?\)")
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
        credential_names: list[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        """
        Validate all template expressions in a workflow.

        Args:
            workflow_spec: Workflow specification
            form_fields: List of valid form field names
            step_ids: List of valid step IDs
            credential_names: Declared ``credentials.uses`` names. When
                non-empty, ``$secret("x")`` references are validated against it.

        Returns:
            Tuple of (warnings, errors)
        """
        self.warnings = []
        self.errors = []

        # Extract and validate all templates
        self._validate_object(
            workflow_spec, form_fields, set(step_ids), set(credential_names or [])
        )

        return self.warnings, self.errors

    def _validate_object(
        self,
        obj: Any,
        form_fields: list[str],
        step_ids: set[str],
        credential_names: set[str],
        path: str = "",
    ) -> None:
        """Recursively validate templates in any object."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                self._validate_object(
                    value,
                    form_fields,
                    step_ids,
                    credential_names,
                    f"{path}.{key}" if path else key,
                )
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                self._validate_object(
                    item, form_fields, step_ids, credential_names, f"{path}[{idx}]"
                )
        elif isinstance(obj, str):
            self._validate_string_templates(obj, form_fields, step_ids, credential_names, path)

    def _validate_string_templates(
        self,
        text: str,
        form_fields: list[str],
        step_ids: set[str],
        credential_names: set[str],
        path: str,
    ) -> None:
        """Validate all template expressions in a string."""
        for match in _TEMPLATE_RE.finditer(text):
            expr = match.group(1).strip()
            self._validate_expression(expr, form_fields, step_ids, credential_names, path)

    def _validate_expression(
        self,
        expr: str,
        form_fields: list[str],
        step_ids: set[str],
        credential_names: set[str],
        path: str,
    ) -> None:
        """Validate every reference in one ``{{ ... }}`` expression.

        A block may hold a compound expression with multiple references, so we
        scan for each ``$step``/``$form``/``$secret``/``$env`` occurrence rather
        than assuming the whole block is a single reference.
        """
        matched_any = False

        # $step() references
        for step_match in _STEP_RE.finditer(expr):
            matched_any = True
            step_id = step_match.group(1)
            prop_path = step_match.group(2) or ""

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

        # $form.<field> references
        for form_match in _FORM_RE.finditer(expr):
            matched_any = True
            field_name = form_match.group(1).split(".")[0]
            if field_name not in form_fields:
                self.warnings.append(
                    f"At {path}: Unknown form field '{field_name}' in template. "
                    f"Available fields: {form_fields}"
                )

        # $secret("name") references — validate against declared credentials.
        for secret_match in _SECRET_RE.finditer(expr):
            matched_any = True
            secret_name = secret_match.group(1)
            if credential_names:
                if secret_name not in credential_names:
                    self.errors.append(
                        f"At {path}: Unknown secret '{secret_name}' in template. "
                        f"Declare it under credentials.uses. "
                        f"Declared: {sorted(credential_names)}"
                    )
            else:
                # No credentials declared at all: cannot validate, but flag it
                # so an undeclared secret does not fail silently at runtime.
                self.warnings.append(
                    f"At {path}: $secret('{secret_name}') used but no "
                    f"credentials.uses are declared."
                )

        # $env() references — cannot be validated at compile time.
        if _ENV_RE.search(expr):
            matched_any = True

        # Unknown expression pattern (only flag if it looks like a directive).
        if not matched_any and expr.startswith("$"):
            self.warnings.append(f"At {path}: Unrecognized template expression '{{{{ {expr} }}}}'")


def validate_templates(
    workflow_spec: dict[str, Any],
    form_fields: list[str],
    step_ids: list[str],
    credential_names: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """
    Validate template expressions in workflow.

    Args:
        workflow_spec: Workflow specification
        form_fields: Valid form field names
        step_ids: Valid step IDs
        credential_names: Declared credentials.uses names (for $secret checks)

    Returns:
        Tuple of (warnings, errors)
    """
    validator = TemplateValidator()
    return validator.validate_workflow(workflow_spec, form_fields, step_ids, credential_names)
