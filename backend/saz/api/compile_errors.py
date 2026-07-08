"""Map compiler ValueErrors to structured CompileError entries.

The compiler currently raises ValueError("workflow step 'x' missing key: y")
style strings. The Guided Builder needs to know which section / step produced
the error so it can highlight the right card. This module parses the known
error formats into `(code, section, step_id, json_pointer)` tuples.

If a message doesn't match any known pattern we still surface it as a
generic `dsl.unknown_error` with section=None — the frontend renders it in
the global error list.
"""

from __future__ import annotations

import re
from typing import Any

from saz.api.schemas.flow_schemas import CompileError

# Each entry: (regex, code, section, step_id_group, json_pointer_template).
# step_id_group is the regex group number that holds the step id, or None.
_PATTERNS: list[tuple[re.Pattern[str], str, str | None, int | None, str | None]] = [
    (
        re.compile(r"workflow step '([^']+)' missing key: (\w+)"),
        "step.missing_field",
        "workflow",
        1,
        "/workflow/steps",
    ),
    (
        re.compile(r"step '([^']+)' .* requires non-empty '(\w+)' field"),
        "step.empty_field",
        "workflow",
        1,
        "/workflow/steps",
    ),
    (
        re.compile(r"step '([^']+)' .* requires '(\w+)' field"),
        "step.missing_field",
        "workflow",
        1,
        "/workflow/steps",
    ),
    (
        re.compile(r"step '([^']+)' params must be an object"),
        "step.params_not_object",
        "workflow",
        1,
        "/workflow/steps",
    ),
    (
        re.compile(r"step '([^']+)' uses_credentials must be"),
        "step.uses_credentials_invalid",
        "workflow",
        1,
        "/workflow/steps",
    ),
    (
        re.compile(r"step '([^']+)' references unknown credentials"),
        "step.unknown_credential",
        "workflow",
        1,
        "/workflow/steps",
    ),
    (
        re.compile(r"step '([^']+)' webhook\.wait requires params\.event_name"),
        "step.webhook_wait_missing_event",
        "workflow",
        1,
        "/workflow/steps",
    ),
    (
        re.compile(r"step '([^']+)' tool '[^']+' missing required params"),
        "step.missing_tool_params",
        "workflow",
        1,
        "/workflow/steps",
    ),
    (
        re.compile(r"Unknown step type '[^']+' in step '([^']+)'"),
        "step.unknown_type",
        "workflow",
        1,
        "/workflow/steps",
    ),
    (
        re.compile(r"Duplicate step id: ([^\s]+)"),
        "step.duplicate_id",
        "workflow",
        1,
        "/workflow/steps",
    ),
    (
        re.compile(r"workflow\.planner_mode is required"),
        "workflow.planner_mode_required",
        "workflow",
        None,
        "/workflow/planner_mode",
    ),
    (
        re.compile(r"workflow\.planner_mode must be"),
        "workflow.planner_mode_invalid",
        "workflow",
        None,
        "/workflow/planner_mode",
    ),
    (
        re.compile(r"workflow\.steps must be non-empty"),
        "workflow.steps_empty",
        "workflow",
        None,
        "/workflow/steps",
    ),
    (
        re.compile(r"retry\.attempts must be >= 0"),
        "retry.attempts_invalid",
        "policies",
        None,
        "/policies/defaults/retry/attempts",
    ),
    (
        re.compile(r"retry\.backoff\."),
        "retry.backoff_invalid",
        "policies",
        None,
        "/policies/defaults/retry/backoff",
    ),
    (
        re.compile(r"policies\.concurrency"),
        "policies.concurrency_invalid",
        "policies",
        None,
        "/policies/concurrency",
    ),
    (
        re.compile(r"^Invalid YAML"),
        "yaml.invalid",
        None,
        None,
        None,
    ),
]


def value_error_to_compile_error(exc: ValueError) -> CompileError:
    """Turn a compiler ValueError into a structured CompileError.

    Multiple ValueErrors per compile are not currently emitted by the
    compiler (it short-circuits on the first), but the response model
    accepts a list so future compilers can return more than one.
    """

    message = str(exc)
    for pattern, code, section, step_group, pointer in _PATTERNS:
        m = pattern.search(message)
        if not m:
            continue
        step_id: str | None = None
        if step_group is not None and m.groups():
            try:
                step_id = m.group(step_group)
            except IndexError:
                step_id = None
        return CompileError(
            code=code,
            message=message,
            section=section,
            step_id=step_id,
            json_pointer=pointer,
        )

    return CompileError(
        code="dsl.unknown_error",
        message=message,
        section=None,
        step_id=None,
        json_pointer=None,
    )


def safe_compile_response(
    yaml_content: str,
) -> tuple[Any | None, list[CompileError]]:
    """Run the DSL compiler and catch ValueErrors as structured entries.

    Returns (compiled, []) on success or (None, [error]) on failure. We
    intentionally do not catch other exception types here — those are bugs
    and should surface as 500s rather than as user-visible compile errors.
    """

    from saz.compiler import compile_dsl

    try:
        compiled = compile_dsl(yaml_content)
        return compiled, []
    except ValueError as exc:
        return None, [value_error_to_compile_error(exc)]
