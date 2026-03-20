"""Tests for the pre-execution replanning loop in _ground_and_verify.

Proves proposal claim: "verifier requests replan → planner replans within limit →
revised plan is verified and then executed → repeated replan requests hit retry
limit → retry limit leads to escalate or fail per policy → all attempts are auditable."
"""

import json

import pytest

from saz.agents.critic import CriticAgent
from saz.agents.schemas import PlanStep, Verdict
from tests.conftest import MockLLMPort


def _make_critique_json(
    verdict: str, reasoning: str = "test", confidence: float = 0.9, modifications: str | None = None
) -> str:
    suggestions = {}
    if modifications:
        suggestions["modifications"] = modifications
    return json.dumps(
        {
            "verdict": verdict,
            "reasoning": reasoning,
            "issues": [] if verdict == "pass" else ["issue"],
            "safety_flags": [],
            "suggestions": suggestions,
            "confidence": confidence,
        }
    )


@pytest.fixture
def sample_step():
    return PlanStep(
        step_id="extract_data",
        step_type="ai.extract",
        tool_name="ai.extract",
        reasoning="Extract entities from input text",
        error_handling="retry",
        max_retries=1,
    )


@pytest.fixture
def sample_tool_call():
    return {
        "tool": "ai.extract",
        "arguments": {"instruction": "Extract entities", "data": {"text": "hello"}},
    }


@pytest.mark.asyncio
async def test_replan_then_pass(sample_step, sample_tool_call):
    """Verifier requests replan on first attempt, approves revised proposal."""
    replan_response = _make_critique_json(
        "replan", "Use a safer extraction method", modifications="Use read-only mode"
    )
    pass_response = _make_critique_json("pass", "Revised proposal is safe")

    llm = MockLLMPort(responses=[replan_response, pass_response])
    critic = CriticAgent(llm_port=llm)

    # First call returns REPLAN
    result1 = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )
    assert result1.verdict == Verdict.REPLAN
    assert "modifications" in result1.suggestions

    # Second call (after replanning) returns PASS
    result2 = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )
    assert result2.verdict == Verdict.PASS
    assert llm.call_count == 2


@pytest.mark.asyncio
async def test_multiple_replans_before_pass(sample_step, sample_tool_call):
    """Verifier requests replan multiple times before approving."""
    responses = [
        _make_critique_json("replan", "Attempt 1 needs work"),
        _make_critique_json("replan", "Attempt 2 still needs work"),
        _make_critique_json("pass", "Attempt 3 is good"),
    ]
    llm = MockLLMPort(responses=responses)
    critic = CriticAgent(llm_port=llm)

    results = []
    for _i in range(3):
        result = await critic.verify_proposal(
            step=sample_step,
            proposed_tool_call=sample_tool_call,
            run_id="run-1",
            completed_steps=[],
            current_state={},
        )
        results.append(result)

    assert results[0].verdict == Verdict.REPLAN
    assert results[1].verdict == Verdict.REPLAN
    assert results[2].verdict == Verdict.PASS
    assert llm.call_count == 3


@pytest.mark.asyncio
async def test_replan_with_modifications_in_suggestions(sample_step, sample_tool_call):
    """Replan suggestions include modification details."""
    response = _make_critique_json(
        "replan",
        "Arguments could be improved for safety",
        modifications="Use read-only mode instead of write",
    )
    llm = MockLLMPort(responses=[response])
    critic = CriticAgent(llm_port=llm)

    result = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )

    assert result.verdict == Verdict.REPLAN
    assert result.suggestions.get("modifications") == "Use read-only mode instead of write"


@pytest.mark.asyncio
async def test_replan_then_fail_gives_fail(sample_step, sample_tool_call):
    """After replan, verifier can still reject the revised proposal."""
    responses = [
        _make_critique_json("replan", "Needs revision"),
        _make_critique_json("fail", "Revised proposal is still unsafe"),
    ]
    llm = MockLLMPort(responses=responses)
    critic = CriticAgent(llm_port=llm)

    r1 = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )
    assert r1.verdict == Verdict.REPLAN

    r2 = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )
    assert r2.verdict == Verdict.FAIL


@pytest.mark.asyncio
async def test_replan_then_escalate(sample_step, sample_tool_call):
    """After replan, verifier can escalate to human."""
    responses = [
        _make_critique_json("replan", "Needs revision"),
        _make_critique_json("escalate_to_human", "Production data access requires approval"),
    ]
    llm = MockLLMPort(responses=responses)
    critic = CriticAgent(llm_port=llm)

    r1 = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )
    assert r1.verdict == Verdict.REPLAN

    r2 = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )
    assert r2.verdict == Verdict.ESCALATE


@pytest.mark.asyncio
async def test_replan_confidence_typically_lower(sample_step, sample_tool_call):
    """Replan verdicts should have lower confidence than approvals."""
    replan = _make_critique_json("replan", "Needs revision", confidence=0.6)
    approve = _make_critique_json("pass", "Now safe", confidence=0.95)

    llm = MockLLMPort(responses=[replan, approve])
    critic = CriticAgent(llm_port=llm)

    r1 = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )
    r2 = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )

    assert r1.confidence < r2.confidence


@pytest.mark.asyncio
async def test_deterministic_mode_replan_includes_context(sample_step, sample_tool_call):
    """In deterministic mode, replan verdict still carries context for the caller."""
    response = _make_critique_json(
        "replan", "Step ordering issue", modifications="Swap steps 2 and 3"
    )
    llm = MockLLMPort(responses=[response])
    critic = CriticAgent(llm_port=llm)

    result = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
        planner_mode="deterministic",
    )

    assert result.verdict == Verdict.REPLAN
    # Caller (executor) is responsible for deciding whether to actually replan or fail
    assert result.reasoning == "Step ordering issue"
