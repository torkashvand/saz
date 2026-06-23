"""Deterministic rule: every {{ $form.x }} / {{ $step('id') }} reference must
resolve to a real form field or an earlier step.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from saz.linter.context import LintContext, StepView
from saz.linter.findings import LintCode, LintFinding, Severity

_EXPR = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_FORM_REF = re.compile(r"\$form\.([A-Za-z_][A-Za-z0-9_]*)")
_STEP_REF = re.compile(r"\$step\(\s*['\"]([^'\"]+)['\"]\s*\)")


def _walk_strings(value: Any, top_key: str) -> Iterator[tuple[str, str]]:
    """Yield (top_level_field, string) for every string under a step value."""
    if isinstance(value, str):
        yield top_key, value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _walk_strings(v, top_key)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_strings(v, top_key)


class TemplateRefsRule:
    code_prefix = "TEMPLATE_REF"

    def check(self, ctx: LintContext) -> list[LintFinding]:
        all_ids = {s.step_id for s in ctx.steps if s.raw.get("id")}
        findings: list[LintFinding] = []
        for step in ctx.steps:
            findings.extend(self._check_step(ctx, step, all_ids))
        return findings

    def _check_step(self, ctx: LintContext, step: StepView, all_ids: set[str]) -> list[LintFinding]:
        out: list[LintFinding] = []
        prior = set(step.prior_step_ids)
        for top_key, text in _walk_strings(step.raw, ""):
            for expr_match in _EXPR.finditer(text):
                expr = expr_match.group(1)
                field = top_key or None

                for fm in _FORM_REF.finditer(expr):
                    fname = fm.group(1)
                    if fname not in ctx.form_fields:
                        out.append(
                            LintFinding(
                                code=LintCode.TEMPLATE_REF_UNKNOWN_FORM_FIELD,
                                severity=Severity.ERROR,
                                step_id=step.step_id,
                                field=field,
                                message=(
                                    f"References $form.{fname}, but no form field "
                                    f"named {fname!r} is defined."
                                ),
                                suggested_fix=("Add the field to form.fields or fix the name."),
                                source="deterministic",
                            )
                        )

                for sm in _STEP_REF.finditer(expr):
                    sid = sm.group(1)
                    if sid not in all_ids:
                        out.append(
                            LintFinding(
                                code=LintCode.TEMPLATE_REF_UNKNOWN_STEP,
                                severity=Severity.ERROR,
                                step_id=step.step_id,
                                field=field,
                                message=(
                                    f"References $step('{sid}'), but no step with "
                                    f"id {sid!r} exists."
                                ),
                                suggested_fix="Fix the step id.",
                                source="deterministic",
                            )
                        )
                    elif sid not in prior:
                        out.append(
                            LintFinding(
                                code=LintCode.TEMPLATE_REF_FORWARD_STEP,
                                severity=Severity.ERROR,
                                step_id=step.step_id,
                                field=field,
                                message=(
                                    f"References $step('{sid}'), which runs at or "
                                    "after this step; only earlier steps are in scope."
                                ),
                                suggested_fix=("Reference a step that runs before this one."),
                                source="deterministic",
                            )
                        )
        return out
