"""Unit tests for the Approval Brief Service."""

import json

import pytest

from saz.agents.ai_ops import AIOperationsRunner
from saz.agents.llm_port import LLMPort, LLMResponse
from saz.services.approval_brief import (
    ApprovalBriefService,
    ApprovalEvidence,
    build_fallback_brief,
)
from tests.conftest import MockLLMPort

VALID_BRIEF = json.dumps(
    {
        "decision_title": "Approve moving this RFQ package to draft generation?",
        "readiness": "ready",
        "readiness_label": "Ready for approval",
        "main_reason": "Validation and PONT checks passed with no blocking issues.",
        "critical_issues": [],
        "passed_checks": ["No missing fields", "PONT check passed"],
        "key_facts": [{"label": "Project", "value": "HR Information System"}],
        "approval_consequence": "If approved, Saz will draft the RFQ document.",
        "confidence": 0.8,
    }
)


class _RaisingLLM(LLMPort):
    async def complete(self, *args, **kwargs) -> LLMResponse:  # type: ignore[override]
        raise RuntimeError("llm exploded")


def _runner(*responses: str) -> AIOperationsRunner:
    return AIOperationsRunner(llm_port=MockLLMPort(list(responses)), default_model="test")


def _evidence(**overrides) -> ApprovalEvidence:
    base = dict(
        approval_step_id="procurement_review",
        approval_description="Review the RFQ narrative before drafting.",
        reasoning="Procurement officer sign-off required.",
        payload={
            "project_name": "HR Information System",
            "criticality": "high",
            "estimated_value_eur": 30000,
            "api_key": "SUPERSECRETVALUE12345",
        },
        completed_steps=[
            {
                "id": "validate_inputs",
                "step_type": "ai.extract",
                "output": {"missing_fields": [], "inconsistencies": []},
            },
            {
                "id": "pont_check",
                "step_type": "ai.evaluate",
                "output": {"pass": True, "issues": []},
            },
        ],
        next_steps=[
            {"id": "render_draft", "step_type": "tool.call"},
            {"id": "store_artifact", "step_type": "artifact.store"},
        ],
    )
    base.update(overrides)
    return ApprovalEvidence(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_generate_returns_structured_brief_with_source_ids():
    service = ApprovalBriefService(runner=_runner(VALID_BRIEF))
    brief = await service.generate(_evidence())

    assert brief.generation_status == "generated"
    assert brief.decision_title.startswith("Approve")
    assert brief.readiness == "ready"
    # source_step_ids is always set by the service from the evidence, not the LLM.
    assert brief.source_step_ids == ["validate_inputs", "pont_check"]
    assert brief.confidence == 0.8


@pytest.mark.asyncio
async def test_generate_includes_structured_checks():
    ev = _evidence(
        completed_steps=[
            {
                "id": "gate_budget",
                "step_type": "condition",
                "output": {"result": True, "condition": "x <= 20000"},
            },
            {
                "id": "pont_check",
                "step_type": "ai.evaluate",
                "output": {"pass": False, "issues": ["criteria not measurable"]},
            },
        ]
    )
    service = ApprovalBriefService(runner=_runner(VALID_BRIEF))
    brief = await service.generate(ev)

    by_label = {c.label: c for c in brief.checks}
    assert by_label["Budget"].status == "passed"
    assert by_label["PONT"].status == "needs_review"
    # The structured shape survives serialization for the frontend.
    stored = brief.to_storage()["checks"]
    assert {"label": "PONT", "status": "needs_review", "detail": "1 concern(s)"} in [
        {k: v for k, v in c.items() if k != "source_step_id"} for c in stored
    ]


def test_fallback_brief_includes_checks():
    ev = _evidence(
        completed_steps=[
            {
                "id": "validate_inputs",
                "step_type": "ai.extract",
                "output": {"missing_fields": ["security_requirements"], "inconsistencies": []},
            },
        ]
    )
    brief = build_fallback_brief(ev)
    by_label = {c.label: c for c in brief.checks}
    assert by_label["Required information"].status == "blocked"
    assert by_label["Consistency"].status == "passed"


@pytest.mark.asyncio
async def test_conservative_floor_blocks_ready_when_pont_failed():
    """A failed PONT check must not be summarized as 'ready'."""
    ev = _evidence(
        completed_steps=[
            {
                "id": "pont_check",
                "step_type": "ai.evaluate",
                "output": {"pass": False, "issues": ["Criteria not measurable"]},
            },
        ]
    )
    service = ApprovalBriefService(runner=_runner(VALID_BRIEF))  # LLM says "ready"
    brief = await service.generate(ev)

    assert brief.readiness == "review_required"
    assert brief.readiness != "ready"
    assert any("automated checks" in w for w in brief.warnings)


@pytest.mark.asyncio
async def test_missing_fields_force_blocked():
    ev = _evidence(
        completed_steps=[
            {
                "id": "validate_inputs",
                "step_type": "ai.extract",
                "output": {"missing_fields": ["security_requirements"]},
            },
        ]
    )
    service = ApprovalBriefService(runner=_runner(VALID_BRIEF))
    brief = await service.generate(ev)
    assert brief.readiness == "blocked"


@pytest.mark.asyncio
async def test_llm_failure_falls_back_without_raising():
    service = ApprovalBriefService(
        runner=AIOperationsRunner(llm_port=_RaisingLLM(), default_model="t")
    )
    brief = await service.generate(_evidence())

    assert brief.generation_status == "fallback"
    assert brief.warnings  # explains AI was unavailable
    assert brief.debug_reason
    # Even the fallback surfaces the source steps and a decision title.
    assert brief.source_step_ids == ["validate_inputs", "pont_check"]
    assert brief.decision_title


@pytest.mark.asyncio
async def test_invalid_json_falls_back():
    service = ApprovalBriefService(runner=_runner("this is not json"))
    brief = await service.generate(_evidence())
    assert brief.generation_status == "fallback"


@pytest.mark.asyncio
async def test_secrets_not_sent_to_llm():
    mock = MockLLMPort([VALID_BRIEF])
    service = ApprovalBriefService(runner=AIOperationsRunner(llm_port=mock, default_model="t"))
    await service.generate(_evidence())

    sent = json.dumps(mock.calls)
    assert "SUPERSECRETVALUE12345" not in sent


def test_fallback_brief_uses_next_steps_for_consequence():
    brief = build_fallback_brief(_evidence())
    assert "render_draft" in brief.approval_consequence
    assert brief.generation_status == "fallback"


def test_fallback_brief_extracts_key_facts_and_skips_secrets():
    brief = build_fallback_brief(_evidence())
    labels = {f.label: f.value for f in brief.key_facts}
    assert labels.get("Project") == "HR Information System"
    assert labels.get("Criticality") == "high"
    # Sensitive payload keys never become key facts.
    assert all("SUPERSECRET" not in f.value for f in brief.key_facts)


def test_fallback_brief_unknown_when_no_signals():
    ev = _evidence(completed_steps=[], next_steps=[])
    brief = build_fallback_brief(ev)
    assert brief.readiness == "unknown"
    assert brief.readiness_label == "Approval required"
    assert "complete" in brief.approval_consequence
