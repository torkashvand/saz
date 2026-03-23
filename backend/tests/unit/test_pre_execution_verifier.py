"""Tests for pre-execution verification (CriticAgent.verify_proposal).

Proves proposal claim D: "planner produces plan, verifier evaluates BEFORE execution,
verifier can approve/reject/replan/escalate, only approved actions execute."
"""

import json

import pytest

from saz.agents.critic import CriticAgent
from saz.agents.schemas import PlanStep, Verdict
from tests.conftest import MockLLMPort


@pytest.fixture
def verifier_pass_response():
    """LLM response approving a proposal."""
    return json.dumps(
        {
            "verdict": "pass",
            "reasoning": "Proposal is safe and aligned with step intent",
            "issues": [],
            "safety_flags": [],
            "suggestions": {"next_action": "proceed"},
            "confidence": 0.95,
        }
    )


@pytest.fixture
def verifier_reject_response():
    """LLM response rejecting a proposal."""
    return json.dumps(
        {
            "verdict": "fail",
            "reasoning": "Proposed tool call uses wrong tool for intent",
            "issues": ["tool_mismatch"],
            "safety_flags": ["wrong_tool"],
            "suggestions": {"next_action": "fail"},
            "confidence": 0.9,
        }
    )


@pytest.fixture
def verifier_replan_response():
    """LLM response requesting replan."""
    return json.dumps(
        {
            "verdict": "replan",
            "reasoning": "Arguments could be improved for safety",
            "issues": ["argument_safety"],
            "safety_flags": [],
            "suggestions": {
                "next_action": "replan",
                "modifications": "Use read-only mode instead of write",
            },
            "confidence": 0.7,
        }
    )


@pytest.fixture
def verifier_escalate_response():
    """LLM response escalating to human."""
    return json.dumps(
        {
            "verdict": "escalate_to_human",
            "reasoning": "Proposed action modifies production data",
            "issues": ["production_modification"],
            "safety_flags": ["production_write"],
            "suggestions": {"next_action": "escalate_to_human"},
            "confidence": 0.6,
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
async def test_verify_proposal_approve(sample_step, sample_tool_call, verifier_pass_response):
    """Verifier approves safe proposal."""
    llm = MockLLMPort(responses=[verifier_pass_response])
    critic = CriticAgent(llm_port=llm)

    result = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
        allowed_tools=["ai.extract", "http_request"],
    )

    assert result.verdict == Verdict.PASS
    assert result.confidence >= 0.9
    assert len(result.issues) == 0


@pytest.mark.asyncio
async def test_verify_proposal_reject(sample_step, sample_tool_call, verifier_reject_response):
    """Verifier rejects unsafe proposal — blocks BEFORE execution."""
    llm = MockLLMPort(responses=[verifier_reject_response])
    critic = CriticAgent(llm_port=llm)

    result = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )

    assert result.verdict == Verdict.FAIL
    assert "wrong tool" in str(result.safety_flags).lower() or len(result.issues) > 0


@pytest.mark.asyncio
async def test_verify_proposal_replan(sample_step, sample_tool_call, verifier_replan_response):
    """Verifier requests replan — proposal not executed."""
    llm = MockLLMPort(responses=[verifier_replan_response])
    critic = CriticAgent(llm_port=llm)

    result = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )

    assert result.verdict == Verdict.REPLAN
    assert "modifications" in result.suggestions


@pytest.mark.asyncio
async def test_verify_proposal_escalate(sample_step, sample_tool_call, verifier_escalate_response):
    """Verifier escalates to human — high-risk operation."""
    llm = MockLLMPort(responses=[verifier_escalate_response])
    critic = CriticAgent(llm_port=llm)

    result = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )

    assert result.verdict == Verdict.ESCALATE
    assert len(result.safety_flags) > 0


@pytest.mark.asyncio
async def test_verify_proposal_receives_allowed_tools(sample_step, sample_tool_call):
    """Verifier receives allowed tools list in its prompt."""
    llm = MockLLMPort(
        responses=[
            json.dumps(
                {
                    "verdict": "pass",
                    "reasoning": "ok",
                    "issues": [],
                    "safety_flags": [],
                    "suggestions": {},
                    "confidence": 0.9,
                }
            )
        ]
    )
    critic = CriticAgent(llm_port=llm)

    await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=["step_0"],
        current_state={"step_0": {"result": "ok"}},
        allowed_tools=["ai.extract", "http_request"],
        planner_mode="agentic",
    )

    # Check that the LLM was called with the right context
    assert llm.call_count == 1
    prompt_content = llm.calls[0]["messages"][0]["content"]
    assert "ai.extract" in prompt_content
    assert "http_request" in prompt_content
    assert "agentic" in prompt_content


@pytest.mark.asyncio
async def test_verify_proposal_failure_returns_escalate(sample_step, sample_tool_call):
    """If verifier LLM call fails, default to ESCALATE (safe fallback)."""
    llm = MockLLMPort(responses=["not valid json"])
    critic = CriticAgent(llm_port=llm)

    result = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )

    assert result.verdict == Verdict.ESCALATE
    assert result.confidence == 0.0
    assert "verifier_failure" in result.safety_flags


@pytest.mark.asyncio
async def test_verify_proposal_is_separate_from_critique(sample_step, sample_tool_call):
    """verify_proposal and critique are distinct methods with different prompts."""
    pass_json = json.dumps(
        {
            "verdict": "pass",
            "reasoning": "Safe to execute",
            "issues": [],
            "safety_flags": [],
            "suggestions": {},
            "confidence": 0.95,
        }
    )
    critique_json = json.dumps(
        {
            "verdict": "pass",
            "reasoning": "Result looks good",
            "issues": [],
            "safety_flags": [],
            "suggestions": {},
            "confidence": 0.9,
        }
    )

    llm = MockLLMPort(responses=[pass_json, critique_json])
    critic = CriticAgent(llm_port=llm)

    # Pre-execution verification
    verify_result = await critic.verify_proposal(
        step=sample_step,
        proposed_tool_call=sample_tool_call,
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )

    # Post-execution critique
    critique_result = await critic.critique(
        step=sample_step,
        tool_call=sample_tool_call,
        result={"output": "extracted data"},
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )

    assert verify_result.verdict == Verdict.PASS
    assert critique_result.verdict == Verdict.PASS
    assert llm.call_count == 2

    # Verify different prompts were used
    verify_prompt = llm.calls[0]["messages"][0]["content"]
    critique_prompt = llm.calls[1]["messages"][0]["content"]
    assert "pre-execution" in verify_prompt.lower()
    assert "post-execution" in critique_prompt.lower()
