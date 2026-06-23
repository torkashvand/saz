"""Parsed, normalized view of a flow for lint rules.

Built once in ``lint_flow`` so rules never re-parse YAML/DSL. Each rule receives
this and returns findings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from saz.linter.findings import LintCode


@dataclass(frozen=True)
class StepView:
    """One workflow step plus its in-scope context."""

    index: int
    step_id: str
    step_type: str
    raw: dict[str, Any]
    # Step ids that run strictly before this one.
    prior_step_ids: tuple[str, ...]
    # Parsed lint_ignore: code -> reason. Codes already validated as members of
    # LintCode (unknown strings are reported separately and excluded here).
    ignore: dict[LintCode, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LintContext:
    """Everything a rule needs about a flow."""

    dsl: dict[str, Any]
    form_fields: frozenset[str]
    steps: tuple[StepView, ...]
    # Raw lint_ignore strings per step id that did NOT match a known LintCode,
    # so a dedicated rule can flag them. Maps step_id -> list of bad code strings.
    unknown_ignore_codes: dict[str, list[str]]

    @classmethod
    def from_dsl(cls, dsl: dict[str, Any]) -> LintContext:
        form_fields = frozenset(
            f["name"]
            for f in ((dsl.get("form") or {}).get("fields") or [])
            if isinstance(f, dict) and f.get("name")
        )

        raw_steps = (dsl.get("workflow") or {}).get("steps") or []
        steps: list[StepView] = []
        unknown_ignore: dict[str, list[str]] = {}
        seen_ids: list[str] = []

        known_codes = {c.value for c in LintCode}
        for idx, step in enumerate(raw_steps):
            if not isinstance(step, dict):
                continue
            step_id = step.get("id") or f"<step {idx}>"
            step_type = step.get("type") or ""

            ignore: dict[LintCode, str] = {}
            bad: list[str] = []
            for entry in step.get("lint_ignore") or []:
                if not isinstance(entry, dict):
                    continue
                code = entry.get("code")
                reason = entry.get("reason") or ""
                if code in known_codes:
                    ignore[LintCode(code)] = reason
                else:
                    bad.append(str(code))
            if bad:
                unknown_ignore[step_id] = bad

            steps.append(
                StepView(
                    index=idx,
                    step_id=step_id,
                    step_type=step_type,
                    raw=step,
                    prior_step_ids=tuple(seen_ids),
                    ignore=ignore,
                )
            )
            if step.get("id"):
                seen_ids.append(step["id"])

        return cls(
            dsl=dsl,
            form_fields=form_fields,
            steps=tuple(steps),
            unknown_ignore_codes=unknown_ignore,
        )
