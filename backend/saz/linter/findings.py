"""Findings data model for the flow linter.

``LintCode`` is a closed enum: every deterministic rule and the LLM consistency
critic must emit a known code. The LLM cannot invent codes (its structured
output is validated against this enum), so overrides (``lint_ignore``) and the
frontend type stay stable.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class LintCode(StrEnum):
    # --- deterministic: template references ---
    TEMPLATE_REF_UNKNOWN_FORM_FIELD = "TEMPLATE_REF_UNKNOWN_FORM_FIELD"
    TEMPLATE_REF_UNKNOWN_STEP = "TEMPLATE_REF_UNKNOWN_STEP"
    TEMPLATE_REF_FORWARD_STEP = "TEMPLATE_REF_FORWARD_STEP"

    # --- deterministic: ai.* prose vs expect schema ---
    PROSE_SCHEMA_COUNT_MISMATCH = "PROSE_SCHEMA_COUNT_MISMATCH"
    PROSE_SCHEMA_ENUM_UNKNOWN = "PROSE_SCHEMA_ENUM_UNKNOWN"
    PROSE_SCHEMA_FIELD_UNKNOWN = "PROSE_SCHEMA_FIELD_UNKNOWN"
    PROSE_SCHEMA_REQUIRED_UNMENTIONED = "PROSE_SCHEMA_REQUIRED_UNMENTIONED"

    # --- deterministic: tool.call params (phase 2) ---
    TOOL_PARAMS_UNKNOWN_KEY = "TOOL_PARAMS_UNKNOWN_KEY"
    TOOL_PARAMS_MISSING_REQUIRED = "TOOL_PARAMS_MISSING_REQUIRED"
    TOOL_PARAMS_TYPE_MISMATCH = "TOOL_PARAMS_TYPE_MISMATCH"

    # --- deterministic: conditions / when guards (phase 2) ---
    CONDITION_PARSE_ERROR = "CONDITION_PARSE_ERROR"
    CONDITION_UNKNOWN_VAR = "CONDITION_UNKNOWN_VAR"
    CONDITION_ARITHMETIC = "CONDITION_ARITHMETIC"

    # --- override hygiene ---
    LINT_IGNORE_UNKNOWN_CODE = "LINT_IGNORE_UNKNOWN_CODE"

    # --- LLM consistency critic (phase 3): closed set ---
    LLM_PROSE_SCHEMA_CONTRADICTION = "LLM_PROSE_SCHEMA_CONTRADICTION"
    LLM_CROSS_FIELD_RULE_UNENFORCED = "LLM_CROSS_FIELD_RULE_UNENFORCED"
    LLM_APPROVAL_MESSAGE_UNSUPPORTED = "LLM_APPROVAL_MESSAGE_UNSUPPORTED"
    LLM_MISSING_INPUT_CONTRACT = "LLM_MISSING_INPUT_CONTRACT"
    LLM_SEMANTIC_AMBIGUITY = "LLM_SEMANTIC_AMBIGUITY"


# Codes the LLM critic is allowed to emit. Used to validate model output and to
# keep the model from inventing codes.
LLM_CODES: frozenset[LintCode] = frozenset(
    {
        LintCode.LLM_PROSE_SCHEMA_CONTRADICTION,
        LintCode.LLM_CROSS_FIELD_RULE_UNENFORCED,
        LintCode.LLM_APPROVAL_MESSAGE_UNSUPPORTED,
        LintCode.LLM_MISSING_INPUT_CONTRACT,
        LintCode.LLM_SEMANTIC_AMBIGUITY,
    }
)


class LintFinding(BaseModel):
    """A single consistency issue found in a flow."""

    model_config = ConfigDict(extra="forbid")

    code: LintCode
    severity: Severity
    step_id: str | None = None
    field: str | None = None
    message: str
    suggested_fix: str | None = None
    source: Literal["deterministic", "llm"]
    confidence: float = 1.0
    suppressed: bool = False
    suppress_reason: str | None = None


class LintReport(BaseModel):
    """Result of linting a flow.

    ``llm_ran`` is False when the LLM rule failed open (model unavailable); in
    that case no LLM finding may block, only surface.
    """

    model_config = ConfigDict(extra="forbid")

    findings: list[LintFinding] = []
    llm_ran: bool = False

    @property
    def blocking(self) -> list[LintFinding]:
        """Findings that must prevent a save.

        ERROR severity, not suppressed, and — for LLM findings — only when the
        LLM actually ran (fail-open).
        """
        out: list[LintFinding] = []
        for f in self.findings:
            if f.severity is not Severity.ERROR or f.suppressed:
                continue
            if f.source == "llm" and not self.llm_ran:
                continue
            out.append(f)
        return out
