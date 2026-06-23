"""Deterministic rule: condition expressions (``if:`` on condition steps and
``when:`` guards on any step) must parse and reference only in-scope variables.
"""

from __future__ import annotations

import re

from saz.engine.expressions import (
    ConditionError,
    extract_condition_refs,
    validate_condition_syntax,
)
from saz.linter.context import LintContext, StepView
from saz.linter.findings import LintCode, LintFinding, Severity

# Arithmetic operators are not in the condition grammar. This check only runs
# AFTER the parser has already rejected the expression, so it only upgrades a
# generic parse error to a friendlier "arithmetic" message. Quoted strings are
# blanked first so "-" / "/" inside string literals don't trigger it; a spaced
# "-" distinguishes subtraction from a negative-number literal.
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_ARITH = re.compile(r"[+*/]|\s-\s")


def _looks_arithmetic(expr: str) -> bool:
    return bool(_ARITH.search(_QUOTED.sub("''", expr)))


class ConditionsRule:
    code_prefix = "CONDITION"

    def check(self, ctx: LintContext) -> list[LintFinding]:
        all_ids = {s.step_id for s in ctx.steps if s.raw.get("id")}
        findings: list[LintFinding] = []
        for step in ctx.steps:
            for field in ("if", "when"):
                expr = step.raw.get(field)
                if isinstance(expr, str) and expr.strip():
                    findings.extend(self._check_expr(ctx, step, field, expr, all_ids))
        return findings

    def _check_expr(
        self,
        ctx: LintContext,
        step: StepView,
        field: str,
        expr: str,
        all_ids: set[str],
    ) -> list[LintFinding]:
        try:
            validate_condition_syntax(expr)
        except ConditionError as exc:
            if _looks_arithmetic(expr):
                return [
                    LintFinding(
                        code=LintCode.CONDITION_ARITHMETIC,
                        severity=Severity.ERROR,
                        step_id=step.step_id,
                        field=field,
                        message=(
                            f"Condition uses arithmetic, which the grammar does not "
                            f"support: {expr!r}."
                        ),
                        suggested_fix="Precompute the value upstream and compare it here.",
                        source="deterministic",
                    )
                ]
            return [
                LintFinding(
                    code=LintCode.CONDITION_PARSE_ERROR,
                    severity=Severity.ERROR,
                    step_id=step.step_id,
                    field=field,
                    message=f"Condition is not valid: {exc}",
                    suggested_fix="Fix the expression syntax.",
                    source="deterministic",
                )
            ]

        out: list[LintFinding] = []
        prior = set(step.prior_step_ids)
        for ref in extract_condition_refs(expr):
            if ref.startswith("$form."):
                fname = ref[len("$form.") :].split(".")[0]
                if fname not in ctx.form_fields:
                    out.append(
                        self._unknown_var(
                            step, field, f"$form.{fname}", f"no form field {fname!r} exists"
                        )
                    )
            elif ref.startswith("$step("):
                m = re.search(r"\$step\(\s*['\"]([^'\"]+)['\"]", ref)
                sid = m.group(1) if m else ""
                if sid not in all_ids:
                    out.append(
                        self._unknown_var(
                            step, field, f"$step('{sid}')", f"no step with id {sid!r} exists"
                        )
                    )
                elif sid not in prior:
                    out.append(
                        self._unknown_var(
                            step,
                            field,
                            f"$step('{sid}')",
                            "that step runs at or after this one",
                        )
                    )
            # $env(...) and $secret(...) resolve at runtime — always in scope.
        return out

    @staticmethod
    def _unknown_var(step: StepView, field: str, ref: str, why: str) -> LintFinding:
        return LintFinding(
            code=LintCode.CONDITION_UNKNOWN_VAR,
            severity=Severity.ERROR,
            step_id=step.step_id,
            field=field,
            message=f"Condition references {ref}, but {why}.",
            suggested_fix="Reference a defined form field or an earlier step.",
            source="deterministic",
        )
