"""LLM consistency critic: parsing, closed-code enforcement, fail-open, de-dup."""

import json

from saz.agents.llm_port import LLMPort, LLMResponse, LLMTransportError
from saz.linter import lint_flow
from saz.linter.findings import LintCode


class _FakeLLM(LLMPort):
    def __init__(self, payload=None, exc=None):
        self._payload = payload
        self._exc = exc

    async def complete(self, *args, **kwargs) -> LLMResponse:  # type: ignore[override]
        if self._exc:
            raise self._exc
        content = self._payload if isinstance(self._payload, str) else json.dumps(self._payload)
        return LLMResponse(content=content, total_tokens=10, model="fake")


def _flow():
    return {
        "workflow": {
            "steps": [
                {
                    "id": "summarize",
                    "type": "ai.extract",
                    "instruction": "Summarize the change; risk_level should respect risk_hint.",
                    "expect": {
                        "type": "object",
                        "properties": {"risk_level": {"type": "string"}},
                    },
                }
            ]
        }
    }


def test_valid_llm_finding_parsed_and_blocks():
    payload = {
        "findings": [
            {
                "code": "LLM_CROSS_FIELD_RULE_UNENFORCED",
                "step_id": "summarize",
                "field": "instruction",
                "message": "risk_hint→risk_level rule not enforceable by schema",
                "suggested_fix": "Constrain in schema or accept in prose",
                "confidence": 0.8,
            }
        ]
    }
    report = lint_flow(_flow(), run_llm=True, llm_port=_FakeLLM(payload))
    assert report.llm_ran is True
    codes = {f.code for f in report.findings}
    assert LintCode.LLM_CROSS_FIELD_RULE_UNENFORCED in codes
    assert len(report.blocking) == 1


def test_ambiguity_is_warning_not_blocking():
    payload = {
        "findings": [{"code": "LLM_SEMANTIC_AMBIGUITY", "step_id": "summarize", "message": "vague"}]
    }
    report = lint_flow(_flow(), run_llm=True, llm_port=_FakeLLM(payload))
    assert report.llm_ran is True
    assert report.blocking == []
    assert any(f.code is LintCode.LLM_SEMANTIC_AMBIGUITY for f in report.findings)


def test_transport_error_fails_open():
    report = lint_flow(
        _flow(), run_llm=True, llm_port=_FakeLLM(exc=LLMTransportError("provider down"))
    )
    assert report.llm_ran is False
    assert report.findings == []  # nothing deterministic in this flow either
    assert report.blocking == []


def test_malformed_json_yields_no_findings_but_llm_ran():
    report = lint_flow(_flow(), run_llm=True, llm_port=_FakeLLM("not json{{"))
    assert report.llm_ran is True
    assert report.findings == []


def test_invented_code_dropped_valid_kept():
    payload = {
        "findings": [
            {"code": "TOTALLY_MADE_UP", "step_id": "summarize", "message": "x"},
            {
                "code": "LLM_PROSE_SCHEMA_CONTRADICTION",
                "step_id": "summarize",
                "message": "real one",
            },
        ]
    }
    report = lint_flow(_flow(), run_llm=True, llm_port=_FakeLLM(payload))
    codes = {f.code for f in report.findings}
    assert LintCode.LLM_PROSE_SCHEMA_CONTRADICTION in codes
    assert len(report.findings) == 1


def test_llm_dedup_against_deterministic():
    # deterministic count mismatch on (summarize, expect.pre_checks); LLM also
    # reports the same (step, field) → LLM dup dropped, but a different-field LLM
    # finding survives.
    flow = {
        "workflow": {
            "steps": [
                {
                    "id": "summarize",
                    "type": "ai.extract",
                    "instruction": '- "pre_checks" is a list (3-6 items).',
                    "expect": {
                        "type": "object",
                        "properties": {
                            "pre_checks": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                            }
                        },
                    },
                }
            ]
        }
    }
    payload = {
        "findings": [
            {
                # real LLM reports the field at a coarser granularity than the
                # deterministic rule ("pre_checks" vs "expect.pre_checks");
                # de-dup must still collapse them.
                "code": "LLM_PROSE_SCHEMA_CONTRADICTION",
                "step_id": "summarize",
                "field": "pre_checks",
                "message": "dup of deterministic",
            },
            {
                "code": "LLM_CROSS_FIELD_RULE_UNENFORCED",
                "step_id": "summarize",
                "field": "instruction",
                "message": "distinct semantic issue",
            },
        ]
    }
    report = lint_flow(flow, run_llm=True, llm_port=_FakeLLM(payload))
    llm_codes = {f.code for f in report.findings if f.source == "llm"}
    assert LintCode.LLM_PROSE_SCHEMA_CONTRADICTION not in llm_codes  # de-duped
    assert LintCode.LLM_CROSS_FIELD_RULE_UNENFORCED in llm_codes  # kept
    assert any(f.code is LintCode.PROSE_SCHEMA_COUNT_MISMATCH for f in report.findings)


def test_llm_fieldless_finding_deduped_when_step_already_flagged():
    # Smaller models (e.g. qwen) often omit the field; a field-less LLM finding
    # on a step that already has a deterministic finding is dropped.
    flow = {
        "workflow": {
            "steps": [
                {
                    "id": "summarize",
                    "type": "ai.extract",
                    "instruction": '- "pre_checks" is a list (3-6 items).',
                    "expect": {
                        "type": "object",
                        "properties": {
                            "pre_checks": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                            }
                        },
                    },
                }
            ]
        }
    }
    payload = {
        "findings": [
            {
                "code": "LLM_PROSE_SCHEMA_CONTRADICTION",
                "step_id": "summarize",
                "field": None,
                "message": "vague restatement of the count mismatch",
            }
        ]
    }
    report = lint_flow(flow, run_llm=True, llm_port=_FakeLLM(payload))
    assert not any(f.source == "llm" for f in report.findings)  # field-less dup dropped
    assert any(f.code is LintCode.PROSE_SCHEMA_COUNT_MISMATCH for f in report.findings)
