"""Approval Brief Service.

Generates a structured, decision-support "approval brief" when a run reaches a
``human.approval`` gate. The brief summarizes the evidence an approver needs —
what they are approving, the readiness state, critical issues, passed checks,
key business facts, and what happens after approval — so the UI can render a
decision packet instead of a raw payload dump.

The AI is a *briefing assistant only*: it summarizes and organizes evidence. It
never decides that approval is safe and never approves or rejects. The final
decision stays human-owned.

Generation never blocks the approval gate: if the LLM fails, times out, or
returns invalid data, a deterministic fallback brief is produced instead.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from saz.agents.ai_ops import AIOperationsRunner
from saz.agents.llm_port import get_llm_port
from saz.security.redaction import is_sensitive_key, redact_sensitive

logger = logging.getLogger(__name__)

ApprovalReadiness = Literal["ready", "review_required", "blocked", "unknown"]
ApprovalGenerationStatus = Literal["generated", "fallback", "failed"]
ApprovalCheckStatus = Literal["passed", "needs_review", "blocked", "unknown"]

# Bound LLM input so a very large run never sends unlimited history to the model.
_MAX_PAYLOAD_CHARS = 2000
_MAX_STEP_OUTPUT_CHARS = 1500

# Keys in step outputs that carry decision-relevant signals. Generic, but
# recognizes the procurement/PONT vocabulary when present.
_BLOCKING_LIST_KEYS = ("missing_fields",)
_CONCERN_LIST_KEYS = ("inconsistencies", "issues", "risks")

# Payload fields surfaced as key business facts in the fallback brief. Generic
# enough to no-op on non-procurement runs (only present keys are shown).
_FACT_FIELDS: tuple[tuple[str, str], ...] = (
    ("project_name", "Project"),
    ("estimated_value_eur", "Estimated value"),
    ("criticality", "Criticality"),
    ("data_sensitivity", "Data sensitivity"),
    ("num_users", "Users"),
    ("contract_duration", "Contract duration"),
    ("vendor_constraints", "Vendor constraints"),
    ("pricing_model", "Pricing model"),
)

_READINESS_RANK = {"ready": 1, "review_required": 2, "blocked": 3}
_READINESS_LABELS: dict[str, str] = {
    "ready": "Ready for approval",
    "review_required": "Review required",
    "blocked": "Blocked — review required",
    "unknown": "Approval required",
}


class ApprovalKeyFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str


class ApprovalCheck(BaseModel):
    """A single named check the approver should weigh (e.g. Budget, PONT)."""

    model_config = ConfigDict(extra="forbid")

    label: str
    status: ApprovalCheckStatus
    detail: str | None = None
    source_step_id: str | None = None


class ApprovalBrief(BaseModel):
    """The structured brief stored on the suspended approval step."""

    model_config = ConfigDict(extra="forbid")

    decision_title: str
    readiness: ApprovalReadiness
    readiness_label: str
    main_reason: str
    critical_issues: list[str] = Field(default_factory=list)
    passed_checks: list[str] = Field(default_factory=list)
    checks: list[ApprovalCheck] = Field(default_factory=list)
    key_facts: list[ApprovalKeyFact] = Field(default_factory=list)
    approval_consequence: str
    source_step_ids: list[str] = Field(default_factory=list)
    generation_status: ApprovalGenerationStatus
    confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)
    debug_reason: str | None = None

    def to_storage(self) -> dict[str, Any]:
        """Serialize for persistence on ``step.input['approval_brief']``."""
        return self.model_dump(exclude_none=True)


@dataclass
class ApprovalEvidence:
    """Evidence gathered from the run when an approval gate is reached."""

    approval_step_id: str
    approval_description: str | None
    reasoning: str | None
    payload: dict[str, Any]
    completed_steps: list[dict[str, Any]] = field(default_factory=list)
    next_steps: list[dict[str, Any]] = field(default_factory=list)

    @property
    def source_step_ids(self) -> list[str]:
        return [s["id"] for s in self.completed_steps if s.get("id")]


# JSON schema steering the LLM. The service attaches source_step_ids /
# generation_status itself, so the model is not asked for them.
_LLM_BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decision_title": {"type": "string"},
        "readiness": {
            "type": "string",
            "enum": ["ready", "review_required", "blocked", "unknown"],
        },
        "readiness_label": {"type": "string"},
        "main_reason": {"type": "string"},
        "critical_issues": {"type": "array", "items": {"type": "string"}},
        "passed_checks": {"type": "array", "items": {"type": "string"}},
        "key_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["label", "value"],
            },
        },
        "approval_consequence": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "decision_title",
        "readiness",
        "readiness_label",
        "main_reason",
        "critical_issues",
        "passed_checks",
        "key_facts",
        "approval_consequence",
    ],
}

_BRIEF_INSTRUCTION = (
    "You are writing a sharp, decision-oriented approval brief for a human "
    "approver deciding whether to let a workflow continue. Use ONLY the supplied "
    "run payload and step outputs. Do not invent facts, numbers, or outcomes. Do "
    "NOT approve or reject — only summarize. Never hide a failed check or turn "
    "uncertainty into confidence. Set readiness to one of ready, review_required, "
    "blocked, unknown; if a check failed or required information is missing it "
    "must be review_required or blocked, never ready.\n\n"
    "decision_title: a plain-language question about the BUSINESS decision (e.g. "
    "'Approve final procurement sign-off for the HR Information System?'). Never "
    "use implementation language (no 'render template', 'store artifact', step "
    "ids).\n"
    "readiness_label: one short phrase summarizing the decision STATE and why it "
    "matters — not merely that a check failed. Prefer wording like 'Review "
    "required — procurement principles may not be satisfied.', 'Blocked — "
    "required approval evidence is missing.', or 'Ready for approval.'\n"
    "main_reason: one sentence explaining the RISK the approver would accept, "
    "e.g. 'The RFQ can continue only if the approver accepts the PONT concerns "
    "around proportionality, objective criteria, non-discrimination, and "
    "transparency.' Do not merely restate that a check failed.\n"
    "critical_issues: only concrete, actionable issues — each a specific concern. "
    "Do NOT include summary lines like 'PONT check failed' or 'review required'; "
    "those belong in readiness_label, not here.\n"
    "passed_checks: short positive checks only.\n"
    "key_facts: the few most important business facts as short label/value "
    "pairs; never long prose (objective/scope/background belong elsewhere).\n"
    "approval_consequence: one plain-language sentence on what Saz will do after "
    "approval, described in user terms derived from the planned next steps (e.g. "
    "'If approved, Saz will generate the final RFQ document and store the RFQ "
    "artifact.'). If the next steps are unknown, say 'If approved, Saz will "
    "continue the workflow after this sign-off.' Never say 'continue to the next "
    "steps'.\n"
    "Do not repeat the same failed-check wording across readiness_label, "
    "main_reason, and critical_issues. Keep everything concise. Return only JSON "
    "matching the schema."
)


def _cap(value: Any, limit: int) -> Any:
    """Return value untouched if small, else a truncated JSON string."""
    try:
        serialized = json.dumps(value, default=str)
    except (TypeError, ValueError):
        serialized = str(value)
    if len(serialized) <= limit:
        return value
    return serialized[:limit] + "…(truncated)"


def _is_scalar(value: Any) -> bool:
    return isinstance(value, str | int | float | bool)


def _deterministic_signals(
    completed_steps: list[dict[str, Any]],
) -> tuple[ApprovalReadiness | None, list[str], list[str]]:
    """Derive a conservative readiness floor plus issues/passed checks.

    Returns ``(floor, critical_issues, passed_checks)`` where floor is the
    minimum readiness the evidence justifies (None when nothing is derivable).
    """
    issues: list[str] = []
    passed: list[str] = []
    has_blocking = False
    has_concern = False

    for step in completed_steps:
        out = step.get("output")
        if not isinstance(out, dict):
            continue

        for key in _BLOCKING_LIST_KEYS:
            val = out.get(key)
            if isinstance(val, list):
                if val:
                    has_blocking = True
                    issues.extend(f"Missing: {v}" for v in val[:5])
                else:
                    passed.append("No missing fields")

        if "pass" in out and isinstance(out["pass"], bool):
            if out["pass"] is False:
                has_concern = True
                issues.append("PONT/compliance check did not pass")
            else:
                passed.append("PONT/compliance check passed")

        for key in _CONCERN_LIST_KEYS:
            val = out.get(key)
            if isinstance(val, list):
                if val:
                    has_concern = True
                    issues.extend(str(v) for v in val[:5])
                elif key == "inconsistencies":
                    passed.append("No inconsistencies")

    floor: ApprovalReadiness | None = (
        "blocked" if has_blocking else ("review_required" if has_concern else None)
    )
    return floor, issues, passed


def _gate_check_label(step_id: str | None) -> str:
    name = (step_id or "check").removeprefix("gate_").replace("_", " ").strip()
    return (name[:1].upper() + name[1:]) if name else "Check"


def _derive_checks(completed_steps: list[dict[str, Any]]) -> list[ApprovalCheck]:
    """Build a compact, reliable pass/needs-review/blocked check list.

    Derived deterministically from step outputs (not model-generated) so the
    statuses are trustworthy. Recognizes the common procurement/validation
    vocabulary; emits nothing for steps with no clear pass/fail signal.
    """
    checks: list[ApprovalCheck] = []
    for step in completed_steps:
        out = step.get("output")
        sid = step.get("id")
        if not isinstance(out, dict):
            continue

        # PONT / compliance evaluation: {pass: bool, issues: [...]}
        if isinstance(out.get("pass"), bool):
            issues = out.get("issues") if isinstance(out.get("issues"), list) else []
            passed = out["pass"]
            checks.append(
                ApprovalCheck(
                    label="PONT",
                    status="passed" if passed else "needs_review",
                    detail=(f"{len(issues)} concern(s)" if (not passed and issues) else None),
                    source_step_id=sid,
                )
            )

        # Deterministic gate condition: {result: bool, condition: "..."}
        if (
            isinstance(out.get("result"), bool)
            and "condition" in out
            and (sid or "").startswith("gate_")
        ):
            checks.append(
                ApprovalCheck(
                    label=_gate_check_label(sid),
                    status="passed" if out["result"] else "needs_review",
                    source_step_id=sid,
                )
            )

        # Required information: missing_fields list (blocking when non-empty)
        if isinstance(out.get("missing_fields"), list):
            mf = out["missing_fields"]
            checks.append(
                ApprovalCheck(
                    label="Required information",
                    status="passed" if not mf else "blocked",
                    detail=(f"{len(mf)} missing" if mf else None),
                    source_step_id=sid,
                )
            )

        # Consistency: inconsistencies list (review when non-empty)
        if isinstance(out.get("inconsistencies"), list):
            inc = out["inconsistencies"]
            checks.append(
                ApprovalCheck(
                    label="Consistency",
                    status="passed" if not inc else "needs_review",
                    detail=(f"{len(inc)} issue(s)" if inc else None),
                    source_step_id=sid,
                )
            )
    return checks


def _extract_key_facts(payload: dict[str, Any]) -> list[ApprovalKeyFact]:
    """Pull a small set of safe scalar business facts from the run payload."""
    facts: list[ApprovalKeyFact] = []
    for key, label in _FACT_FIELDS:
        if key not in payload or is_sensitive_key(key):
            continue
        value = payload[key]
        if value is None or not _is_scalar(value):
            continue
        text = str(value).strip()
        # Skip long free-text values — they belong in advanced details.
        if not text or len(text) > 120:
            continue
        facts.append(ApprovalKeyFact(label=label, value=text))
    return facts


def _consequence_from_next_steps(next_steps: list[dict[str, Any]]) -> str:
    if not next_steps:
        return "If approved, the workflow will complete."
    names = [str(s.get("id")) for s in next_steps[:3] if s.get("id")]
    listed = ", ".join(names) if names else "the remaining steps"
    return f"If approved, Saz will continue with {listed}."


def build_fallback_brief(
    evidence: ApprovalEvidence,
    *,
    debug_reason: str | None = None,
) -> ApprovalBrief:
    """Deterministic brief built without AI when generation is unavailable."""
    floor, issues, passed = _deterministic_signals(evidence.completed_steps)

    title = (evidence.approval_description or "").strip()
    decision_title = title or f"Approve “{evidence.approval_step_id}” to continue?"

    readiness: ApprovalReadiness = floor or "unknown"
    main_reason = (
        title
        or (evidence.reasoning or "").strip()
        or "Human approval is required before this workflow can continue."
    )

    return ApprovalBrief(
        decision_title=decision_title,
        readiness=readiness,
        readiness_label=_READINESS_LABELS[readiness],
        main_reason=main_reason,
        critical_issues=issues[:8],
        passed_checks=passed,
        checks=_derive_checks(evidence.completed_steps),
        key_facts=_extract_key_facts(evidence.payload),
        approval_consequence=_consequence_from_next_steps(evidence.next_steps),
        source_step_ids=evidence.source_step_ids,
        generation_status="fallback",
        warnings=["AI-generated brief was unavailable; showing a basic summary."],
        debug_reason=debug_reason,
    )


class ApprovalBriefService:
    """Generate approval briefs, reusing the existing AI ops / LLM path."""

    def __init__(self, runner: AIOperationsRunner | None = None) -> None:
        self._runner = runner

    def _runner_for_call(self) -> AIOperationsRunner:
        # Build from the current global port each call so tests that override
        # the LLM port (set_llm_port) are honored, not a stale singleton.
        return self._runner or AIOperationsRunner(llm_port=get_llm_port())

    async def generate(self, evidence: ApprovalEvidence) -> ApprovalBrief:
        """Return a brief for the approval gate; never raises."""
        try:
            brief = await self._generate_with_llm(evidence)
        except Exception as exc:  # enrichment must never block the gate
            logger.warning("approval_brief_generation_failed: %s", exc)
            return build_fallback_brief(evidence, debug_reason=str(exc)[:200])

        brief.source_step_ids = evidence.source_step_ids
        brief.generation_status = "generated"
        # Structured checks are derived deterministically from evidence, not the
        # model — reliable statuses for the UI's compact Checks row.
        brief.checks = _derive_checks(evidence.completed_steps)
        self._apply_conservative_floor(brief, evidence.completed_steps)
        return brief

    async def _generate_with_llm(self, evidence: ApprovalEvidence) -> ApprovalBrief:
        runner = self._runner_for_call()
        result = await runner.run_ai_op(
            op_name="ai.extract",
            instruction=_BRIEF_INSTRUCTION,
            data=self._build_llm_input(evidence),
            expected_schema=_LLM_BRIEF_SCHEMA,
            temperature_override=0.1,
            max_tokens_override=1024,
        )
        output = result.get("output")
        if not isinstance(output, dict):
            raise ValueError("LLM returned non-object brief")

        key_facts = [
            ApprovalKeyFact(label=str(f["label"]), value=str(f["value"]))
            for f in output.get("key_facts", [])
            if isinstance(f, dict) and "label" in f and "value" in f
        ]
        return ApprovalBrief(
            decision_title=str(output["decision_title"]),
            readiness=output["readiness"],
            readiness_label=str(output["readiness_label"]),
            main_reason=str(output["main_reason"]),
            critical_issues=[str(x) for x in output.get("critical_issues", [])],
            passed_checks=[str(x) for x in output.get("passed_checks", [])],
            key_facts=key_facts,
            approval_consequence=str(output["approval_consequence"]),
            generation_status="generated",
            confidence=output.get("confidence"),
        )

    def _build_llm_input(self, evidence: ApprovalEvidence) -> dict[str, Any]:
        """Bounded, redacted view of the run for the LLM prompt."""
        return {
            "approval_step": {
                "id": evidence.approval_step_id,
                "description": evidence.approval_description,
                "reasoning": evidence.reasoning,
            },
            "run_payload": _cap(redact_sensitive(evidence.payload), _MAX_PAYLOAD_CHARS),
            "completed_steps": [
                {
                    "id": s.get("id"),
                    "type": s.get("step_type"),
                    "output": _cap(redact_sensitive(s.get("output")), _MAX_STEP_OUTPUT_CHARS),
                }
                for s in evidence.completed_steps
            ],
            "next_steps": [
                {"id": s.get("id"), "type": s.get("step_type")} for s in evidence.next_steps
            ],
        }

    def _apply_conservative_floor(
        self, brief: ApprovalBrief, completed_steps: list[dict[str, Any]]
    ) -> None:
        """Never let the model down-rank a state the evidence says is unsafe."""
        floor, issues, _passed = _deterministic_signals(completed_steps)
        if floor is None:
            return
        current_rank = _READINESS_RANK.get(brief.readiness, 0)
        if brief.readiness == "unknown" or _READINESS_RANK[floor] > current_rank:
            brief.readiness = floor
            brief.readiness_label = _READINESS_LABELS[floor]
            brief.warnings.append("Readiness adjusted to match automated checks.")
            if not brief.critical_issues and issues:
                brief.critical_issues = issues[:5]
