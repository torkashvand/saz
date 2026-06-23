"""LLM consistency critic: finds *semantic* prose↔contract mismatches the
deterministic rules cannot structurally catch (cross-field rules implied in
prose, approval messages promising data no step produces, etc.).

Mirrors CriticAgent: static cacheable system prompt, per-flow evidence in the
user message, strict JSON output validated against a closed code set. Transport
failures propagate as LLMTransportError so the runner can fail open.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict

from saz.agents.llm_port import LLMPort, LLMTransportError
from saz.linter.context import LintContext
from saz.linter.findings import LLM_CODES, LintCode, LintFinding, Severity
from saz.settings import settings

logger = structlog.get_logger(__name__)

_LLM_CODE_VALUES = {c.value for c in LLM_CODES}
# Only ambiguity is advisory; the rest are hard semantic contradictions.
_WARNING_CODES = {LintCode.LLM_SEMANTIC_AMBIGUITY}

CONSISTENCY_SYSTEM_PROMPT = """You are the consistency linter for the Saz workflow engine.

You are given the natural-language text of a flow's steps (AI instructions and
human-approval messages) alongside each step's structured contract (its expected
output JSON schema or available inputs). Your job is to find SEMANTIC
inconsistencies between the prose and the structured contract that a JSON-schema
validator cannot catch.

Report ONLY issues such as:
- A cross-field rule stated in prose that the schema cannot express
  (e.g. "risk_level must be at least the requester's risk_hint").
- Prose describing behavior that contradicts the schema's field types.
- An approval message referencing data that no prior step produces.
- Prose relying on an input that is not an available form field or prior step output.
- Prose so ambiguous it risks inconsistent output.

Do NOT report list-size/count mismatches, enum typos, or unknown template
references — those are handled separately. Do NOT invent issues; if the prose and
contract agree, return an empty list.

Respond with ONLY a JSON object of this exact shape:
{"findings": [
  {"code": <one of: LLM_PROSE_SCHEMA_CONTRADICTION, LLM_CROSS_FIELD_RULE_UNENFORCED,
            LLM_APPROVAL_MESSAGE_UNSUPPORTED, LLM_MISSING_INPUT_CONTRACT,
            LLM_SEMANTIC_AMBIGUITY>,
   "step_id": <string>, "field": <string or null>,
   "message": <short explanation>, "suggested_fix": <short fix or null>,
   "confidence": <number 0..1>}
]}
The "code" MUST be one of the listed values. Return {"findings": []} when consistent."""


class _LLMFindingItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    step_id: str | None = None
    field: str | None = None
    message: str
    suggested_fix: str | None = None
    confidence: float = 0.5


class _LLMOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    findings: list[_LLMFindingItem] = []


class ConsistencyCritic:
    code_prefix = "LLM"

    def __init__(self, llm_port: LLMPort, model: str | None = None):
        self.llm_port = llm_port
        self.model = model or settings.LINT_MODEL or settings.CRITIC_MODEL

    async def check_async(self, ctx: LintContext) -> list[LintFinding]:
        evidence = self._build_evidence(ctx)
        if not evidence:
            return []

        try:
            response = await self.llm_port.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": CONSISTENCY_SYSTEM_PROMPT},
                    {"role": "user", "content": evidence},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
        except LLMTransportError:
            # Propagate: the runner treats this as fail-open (llm_ran=False).
            raise

        return self._parse(response.content)

    def _parse(self, content: str) -> list[LintFinding]:
        try:
            data = json.loads(content)
            output = _LLMOutput.model_validate(data)
        except Exception as exc:  # domain error: untrusted model output
            logger.warning("consistency_critic_parse_failed", error=str(exc))
            return []

        findings: list[LintFinding] = []
        for item in output.findings:
            if item.code not in _LLM_CODE_VALUES:
                # Model invented a code — drop that finding, keep the rest.
                logger.warning("consistency_critic_unknown_code", code=item.code)
                continue
            code = LintCode(item.code)
            severity = Severity.WARNING if code in _WARNING_CODES else Severity.ERROR
            findings.append(
                LintFinding(
                    code=code,
                    severity=severity,
                    step_id=item.step_id,
                    field=item.field,
                    message=item.message,
                    suggested_fix=item.suggested_fix,
                    source="llm",
                    confidence=item.confidence,
                )
            )
        return findings

    @staticmethod
    def _build_evidence(ctx: LintContext) -> str:
        """Static flow-authoring text only (no runtime/PII data)."""
        form_fields = sorted(ctx.form_fields)
        blocks: list[str] = []
        for step in ctx.steps:
            text = step.raw.get("instruction")
            contract: Any = step.raw.get("expect")
            if step.step_type == "human.approval":
                approval = step.raw.get("approval") or {}
                text = " / ".join(
                    str(approval.get(k, "")) for k in ("title", "message") if approval.get(k)
                )
                contract = None
            if not isinstance(text, str) or not text.strip():
                continue
            blocks.append(
                f"### Step '{step.step_id}' (type: {step.step_type})\n"
                f"Available inputs: form fields {form_fields}; "
                f"prior steps {list(step.prior_step_ids)}\n"
                f"Prose:\n{text}\n"
                f"Contract (expected output schema):\n{json.dumps(contract, indent=2)}\n"
            )
        if not blocks:
            return ""
        return "Evaluate these steps for prose↔contract consistency:\n\n" + "\n".join(blocks)
