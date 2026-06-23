"""lint_flow: run all rules over a compiled-and-valid DSL and build the report.

Assumes the DSL already passed ``compile_dsl`` (structure is valid). Deterministic
rules always run; the LLM rule is added in phase 3.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any

from saz.linter.context import LintContext
from saz.linter.findings import LintCode, LintFinding, LintReport, Severity
from saz.linter.rules.ai_prose_schema import AiProseSchemaRule
from saz.linter.rules.base import LintRule
from saz.linter.rules.conditions import ConditionsRule
from saz.linter.rules.template_refs import TemplateRefsRule
from saz.linter.rules.tool_params import ToolParamsRule

if TYPE_CHECKING:
    from saz.agents.llm_port import LLMPort

# Deterministic rules, in display order. New rules are appended here.
_DETERMINISTIC_RULES: list[LintRule] = [
    TemplateRefsRule(),
    AiProseSchemaRule(),
    ToolParamsRule(),
    ConditionsRule(),
]

# Findings of these codes can never be suppressed by lint_ignore — suppressing
# the report of a broken override would defeat the override-hygiene check.
_NON_SUPPRESSIBLE = frozenset({LintCode.LINT_IGNORE_UNKNOWN_CODE})


def lint_flow(
    dsl: dict[str, Any], *, run_llm: bool = True, llm_port: LLMPort | None = None
) -> LintReport:
    ctx = LintContext.from_dsl(dsl)

    findings: list[LintFinding] = []
    for rule in _DETERMINISTIC_RULES:
        findings.extend(rule.check(ctx))

    findings.extend(_unknown_ignore_findings(ctx))

    llm_ran = False
    if run_llm:
        llm_findings, llm_ran = _run_llm_rule(ctx, llm_port)
        findings.extend(_dedup_llm(llm_findings, findings))

    _apply_suppressions(ctx, findings)
    return LintReport(findings=findings, llm_ran=llm_ran)


def _dedup_llm(
    llm_findings: list[LintFinding], deterministic: list[LintFinding]
) -> list[LintFinding]:
    """Drop LLM findings that restate a deterministic finding.

    Two overlap cases, both observed from real models:
    - Same field at different granularity ("pre_checks" vs "expect.pre_checks")
      → match on the trailing field segment.
    - The LLM omits the field (``None``) on a step that already has a
      deterministic finding → almost always the same issue stated vaguely; drop.
    Deterministic findings are authoritative (precise field + message).
    """
    det_keys = {_dedup_key(f) for f in deterministic if f.source == "deterministic"}
    det_steps = {f.step_id for f in deterministic if f.source == "deterministic"}
    kept: list[LintFinding] = []
    for f in llm_findings:
        if _dedup_key(f) in det_keys:
            continue
        if not f.field and f.step_id in det_steps:
            continue
        kept.append(f)
    return kept


def _dedup_key(f: LintFinding) -> tuple[str | None, str | None]:
    """Key for matching findings about the same thing across rule sources.

    Normalizes the field to its trailing segment so "expect.pre_checks"
    (deterministic) and "pre_checks" (LLM) collapse to one issue.
    """
    leaf = f.field.split(".")[-1] if f.field else None
    return (f.step_id, leaf)


def _run_llm_rule(ctx: LintContext, llm_port: LLMPort | None) -> tuple[list[LintFinding], bool]:
    """Run the consistency critic, bridging its async call from sync code.

    Returns (findings, llm_ran). On transport failure the rule fails open:
    no findings, llm_ran=False, so nothing LLM-sourced can block.
    """
    from saz.agents.llm_port import LLMTransportError, get_llm_port
    from saz.linter.rules.llm_consistency import ConsistencyCritic

    port = llm_port or get_llm_port()
    critic = ConsistencyCritic(port)
    try:
        return _run_coro(critic.check_async(ctx)), True
    except LLMTransportError:
        return [], False


def _run_coro(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine to completion from sync code, whether or not an event
    loop is already running in this thread (FastAPI handlers run in one)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


def _unknown_ignore_findings(ctx: LintContext) -> list[LintFinding]:
    out: list[LintFinding] = []
    for step_id, bad_codes in ctx.unknown_ignore_codes.items():
        for code in bad_codes:
            out.append(
                LintFinding(
                    code=LintCode.LINT_IGNORE_UNKNOWN_CODE,
                    severity=Severity.ERROR,
                    step_id=step_id,
                    field="lint_ignore",
                    message=(
                        f"lint_ignore references unknown code {code!r}; the intended "
                        "finding is NOT suppressed. Fix the code or remove the entry."
                    ),
                    suggested_fix="Use a valid LintCode value, or delete the entry.",
                    source="deterministic",
                )
            )
    return out


def _apply_suppressions(ctx: LintContext, findings: list[LintFinding]) -> None:
    ignore_by_step = {s.step_id: s.ignore for s in ctx.steps}
    for f in findings:
        if f.code in _NON_SUPPRESSIBLE or f.step_id is None:
            continue
        reason = ignore_by_step.get(f.step_id, {}).get(f.code)
        if reason is not None:
            f.suppressed = True
            f.suppress_reason = reason
