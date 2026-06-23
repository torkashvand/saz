"""Deterministic rule: a tool.call step's params must satisfy the tool's declared
input schema (required keys present, no unknown keys when the schema is closed,
literal values of the right type/enum).

Skipped silently when the tool registry is not initialized (isolated unit tests);
the executor still fails closed on bad input at grounding.
"""

from __future__ import annotations

from typing import Any

from saz.linter.context import LintContext, StepView
from saz.linter.findings import LintCode, LintFinding, Severity

# JSON schema scalar type -> python isinstance check (bool excluded from numerics).
_SCALAR_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
}


def _is_templated(value: Any) -> bool:
    return isinstance(value, str) and "{{" in value


class ToolParamsRule:
    code_prefix = "TOOL_PARAMS"

    def check(self, ctx: LintContext) -> list[LintFinding]:
        registry = self._registry()
        # No registry, or one that can't expose per-tool schemas — nothing to
        # check (the executor still fails closed on bad input at grounding).
        if registry is None or not hasattr(registry, "get_tool_spec"):
            return []
        findings: list[LintFinding] = []
        for step in ctx.steps:
            if step.step_type != "tool.call":
                continue
            findings.extend(self._check_step(registry, step))
        return findings

    @staticmethod
    def _registry() -> Any:
        try:
            from saz.globals import get_tool_registry

            return get_tool_registry()
        except RuntimeError:
            return None

    def _check_step(self, registry: Any, step: StepView) -> list[LintFinding]:
        tool_name = step.raw.get("tool")
        spec = registry.get_tool_spec(tool_name) if tool_name else None
        if not spec:
            # Unknown/missing tool is handled by _validate_tool_references.
            return []

        schema = spec.get("inputSchema") or spec.get("input_schema") or {}
        props: dict[str, Any] = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        closed = schema.get("additionalProperties") is False

        params = step.raw.get("params")
        if not isinstance(params, dict):
            params = {}

        out: list[LintFinding] = []

        for req in sorted(required - params.keys()):
            out.append(
                self._finding(
                    LintCode.TOOL_PARAMS_MISSING_REQUIRED,
                    step,
                    req,
                    f"Tool '{tool_name}' requires param '{req}', which is missing.",
                    f"Add a '{req}' param.",
                )
            )

        for key, value in params.items():
            if key not in props:
                if closed:
                    out.append(
                        self._finding(
                            LintCode.TOOL_PARAMS_UNKNOWN_KEY,
                            step,
                            key,
                            f"Tool '{tool_name}' has no param '{key}'.",
                            f"Remove '{key}' or check the tool's parameters.",
                        )
                    )
                continue
            mismatch = self._type_mismatch(props[key], value)
            if mismatch:
                out.append(
                    self._finding(
                        LintCode.TOOL_PARAMS_TYPE_MISMATCH,
                        step,
                        key,
                        f"Param '{key}' of '{tool_name}' {mismatch}.",
                        "Fix the value type.",
                    )
                )
        return out

    @staticmethod
    def _type_mismatch(prop_schema: dict[str, Any], value: Any) -> str | None:
        # Only literal (non-templated) scalars are checked — templated values
        # resolve to arbitrary types at runtime.
        if _is_templated(value) or isinstance(value, dict | list):
            return None
        enum = prop_schema.get("enum")
        if enum is not None and not _is_templated(value) and value not in enum:
            return f"must be one of {enum}, got {value!r}"
        ptype = prop_schema.get("type")
        check = _SCALAR_CHECKS.get(ptype) if isinstance(ptype, str) else None
        if check is not None and not check(value):
            return f"must be {ptype}, got {type(value).__name__}"
        return None

    @staticmethod
    def _finding(code: LintCode, step: StepView, key: str, message: str, fix: str) -> LintFinding:
        return LintFinding(
            code=code,
            severity=Severity.ERROR,
            step_id=step.step_id,
            field=f"params.{key}",
            message=message,
            suggested_fix=fix,
            source="deterministic",
        )
