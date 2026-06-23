"""Deterministic rule: an ai.* step's prose must not state list-size bounds that
its ``expect`` schema fails to enforce or contradicts.

Phase 1 implements PROSE_SCHEMA_COUNT_MISMATCH only — the exact class of bug that
shipped in change_approval_ansible (prose "3-6 items" vs schema minItems:1).
Association is deliberately tight (one array field + one quantifier per prose
bullet) so the check is high-precision and safe to block on. Fuzzier prose↔schema
semantics are left to the LLM consistency critic (phase 3).
"""

from __future__ import annotations

import re
from typing import Any

from saz.linter.context import LintContext, StepView
from saz.linter.findings import LintCode, LintFinding, Severity

# Quantifier patterns, highest-priority first. Each returns (min, max) with None
# for an unspecified bound.
_RANGE = re.compile(r"(\d+)\s*(?:-|–|—|to)\s*(\d+)")
_BETWEEN = re.compile(r"between\s+(\d+)\s+and\s+(\d+)", re.IGNORECASE)
_EXACTLY = re.compile(r"exactly\s+(\d+)", re.IGNORECASE)
_AT_LEAST = re.compile(r"(?:at least|minimum of)\s+(\d+)|(\d+)\s+or more", re.IGNORECASE)
_AT_MOST = re.compile(r"(?:up to|at most|maximum of)\s+(\d+)", re.IGNORECASE)


def _parse_quantifier(text: str) -> tuple[int | None, int | None] | None:
    m = _BETWEEN.search(text) or _RANGE.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _EXACTLY.search(text)
    if m:
        n = int(m.group(1))
        return n, n
    m = _AT_LEAST.search(text)
    if m:
        return int(m.group(1) or m.group(2)), None
    m = _AT_MOST.search(text)
    if m:
        return None, int(m.group(1))
    return None


def _bullets(instruction: str) -> list[str]:
    """Group prose into bullets so a quantifier is associated only with the field
    named in the same bullet. Non-bulleted text is one block."""
    lines = instruction.splitlines()
    bullets: list[str] = []
    cur: list[str] = []
    for line in lines:
        if line.lstrip().startswith("-"):
            if cur:
                bullets.append(" ".join(cur))
            cur = [line.strip().lstrip("-").strip()]
        elif cur:
            cur.append(line.strip())
    if cur:
        bullets.append(" ".join(cur))
    if not bullets:
        return [instruction]
    return bullets


def _array_props(expect: dict[str, Any]) -> dict[str, dict[str, Any]]:
    props = expect.get("properties") or {}
    out: dict[str, dict[str, Any]] = {}
    for name, schema in props.items():
        if isinstance(schema, dict) and schema.get("type") == "array":
            out[name] = schema
    return out


class AiProseSchemaRule:
    code_prefix = "PROSE_SCHEMA"

    def check(self, ctx: LintContext) -> list[LintFinding]:
        findings: list[LintFinding] = []
        for step in ctx.steps:
            if not step.step_type.startswith("ai."):
                continue
            findings.extend(self._check_step(step))
        return findings

    def _check_step(self, step: StepView) -> list[LintFinding]:
        instruction = step.raw.get("instruction")
        expect = step.raw.get("expect")
        if not isinstance(instruction, str) or not isinstance(expect, dict):
            return []

        array_props = _array_props(expect)
        if not array_props:
            return []

        out: list[LintFinding] = []
        for bullet in _bullets(instruction):
            mentioned = [p for p in array_props if p in bullet]
            if len(mentioned) != 1:
                # 0 or >1 array fields in this bullet → ambiguous association, skip.
                continue
            prop = mentioned[0]
            q = _parse_quantifier(bullet)
            if q is None:
                continue
            pmin, pmax = q
            schema = array_props[prop]
            smin = schema.get("minItems")
            smax = schema.get("maxItems")

            problems = self._contradictions(pmin, pmax, smin, smax)
            if problems:
                out.append(
                    LintFinding(
                        code=LintCode.PROSE_SCHEMA_COUNT_MISMATCH,
                        severity=Severity.ERROR,
                        step_id=step.step_id,
                        field=f"expect.{prop}",
                        message=(
                            f"Prose says '{prop}' should have "
                            f"{self._fmt_bound(pmin, pmax)} items, but the schema "
                            f"enforces {self._fmt_schema(smin, smax)}. " + " ".join(problems)
                        ),
                        suggested_fix=(
                            f"Set {prop}.minItems/maxItems to match the prose "
                            f"({self._fmt_schema(pmin, pmax)})."
                        ),
                        source="deterministic",
                    )
                )
        return out

    @staticmethod
    def _contradictions(
        pmin: int | None, pmax: int | None, smin: int | None, smax: int | None
    ) -> list[str]:
        problems: list[str] = []
        if pmin is not None and (smin is None or smin < pmin):
            problems.append(f"Schema permits fewer than {pmin} items, which the prose forbids.")
        if pmax is not None and (smax is None or smax > pmax):
            problems.append(f"Schema permits more than {pmax} items, which the prose forbids.")
        if smin is not None and pmax is not None and smin > pmax:
            problems.append(
                f"Schema requires at least {smin}, exceeding the prose maximum of {pmax}."
            )
        if smax is not None and pmin is not None and smax < pmin:
            problems.append(f"Schema caps at {smax}, below the prose minimum of {pmin}.")
        return problems

    @staticmethod
    def _fmt_bound(lo: int | None, hi: int | None) -> str:
        if lo is not None and hi is not None:
            return f"{lo}-{hi}" if lo != hi else f"exactly {lo}"
        if lo is not None:
            return f"at least {lo}"
        if hi is not None:
            return f"up to {hi}"
        return "an unspecified number of"

    @staticmethod
    def _fmt_schema(lo: int | None, hi: int | None) -> str:
        parts = []
        parts.append(f"minItems={lo if lo is not None else 'unset'}")
        parts.append(f"maxItems={hi if hi is not None else 'unset'}")
        return ", ".join(parts)
