"""Regression tests for the pre-execution verifier on ai.* tool calls.

Context: the verifier prompt previously told the LLM to flag missing
"required arguments" without clarifying that for ai.* operations the
``expected_schema`` defines the OUTPUT contract, not required *input*
fields. The result was a real failure mode:

  * Step has a strict `expect` schema (every wedge demo does).
  * Verifier reads the proposal and sees `expected_schema.properties =
    {blast_radius, ready_to_proceed, ...}`.
  * Verifier compares those names against `data` keys and emits REPLAN
    with "data is missing blast_radius/ready_to_proceed".
  * Deterministic mode treats REPLAN as fatal — the run dies before any
    AI op ever fires.

This test file pins the prompt-level fix so it cannot silently regress.
"""

from __future__ import annotations

import json

import pytest

from saz.agents.critic import VERIFIER_SYSTEM_PROMPT, CriticAgent
from saz.agents.schemas import ErrorHandling, PlanStep, Verdict
from tests.conftest import MockLLMPort


def test_verifier_prompt_explains_ai_op_contract():
    """The verifier prompt must explicitly tell the LLM that
    expected_schema is the OUTPUT contract, not a required-input list,
    so it stops flagging ai.* calls as missing arguments."""
    # Cover the key invariants we depend on. If any of these strings
    # disappear from the prompt, the verifier will regress to the
    # broken behaviour that killed every ai.* step in deterministic
    # mode.
    assert "ai." in VERIFIER_SYSTEM_PROMPT
    assert "expected_schema" in VERIFIER_SYSTEM_PROMPT
    assert "OUTPUT" in VERIFIER_SYSTEM_PROMPT
    # The most important rule: do not compare expected_schema property
    # names against the keys of `data`.
    assert "Do NOT compare" in VERIFIER_SYSTEM_PROMPT
    assert "expected_schema" in VERIFIER_SYSTEM_PROMPT.split("Do NOT compare", 1)[1][:200]
    # And the non-ai branch must still demand required arguments.
    assert "non-ai tools" in VERIFIER_SYSTEM_PROMPT


def _ai_extract_step() -> PlanStep:
    return PlanStep(
        step_id="validate_maintenance_plan",
        step_type="ai.extract",
        tool_name="ai.extract",
        reasoning="Review the maintenance request and produce a JSON object",
        error_handling=ErrorHandling.RETRY,
        max_retries=1,
    )


def _ai_extract_proposal() -> dict:
    """A realistic proposal mirroring what the wedge demos generate:
    `data` contains operator inputs (title, target_system, environment...),
    and `expected_schema` declares the OUTPUT fields (blast_radius,
    preconditions, ready_to_proceed). The two key-sets DELIBERATELY do
    not overlap — that's the case the old verifier mistakenly flagged."""
    return {
        "tool": "ai.extract",
        "arguments": {
            "instruction": "Review the maintenance request and produce a JSON object...",
            "data": {
                "title": "Edge cache rebuild",
                "target_system": "edge-cache",
                "environment": "staging",
                "window": "2026-05-20 02:00-04:00 UTC",
            },
            "expected_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "intent_summary": {"type": "string"},
                    "blast_radius": {"type": "string"},
                    "preconditions": {"type": "array"},
                    "ready_to_proceed": {"type": "boolean"},
                },
                "required": [
                    "intent_summary",
                    "blast_radius",
                    "preconditions",
                    "ready_to_proceed",
                ],
            },
        },
    }


@pytest.mark.asyncio
async def test_verifier_prompt_renders_ai_op_proposal_without_error():
    """End-to-end: the verifier formats the prompt with a realistic
    ai.extract proposal, calls the LLM, parses the (mocked) PASS
    response, and returns Verdict.PASS. This confirms the new prompt
    template still substitutes cleanly for the most demo-critical
    proposal shape."""
    pass_response = json.dumps(
        {
            "verdict": "pass",
            "reasoning": (
                "Proposal is well-formed: instruction is concrete, data carries "
                "the operator inputs, and the expected_schema is an OUTPUT "
                "contract enforced by the AI op runtime — not by this verifier."
            ),
            "issues": [],
            "safety_flags": [],
            "suggestions": {"next_action": "execute"},
            "confidence": 0.95,
        }
    )
    llm = MockLLMPort(responses=[pass_response])
    critic = CriticAgent(llm_port=llm)

    result = await critic.verify_proposal(
        step=_ai_extract_step(),
        proposed_tool_call=_ai_extract_proposal(),
        run_id="run-verifier-ai-contract",
        completed_steps=[],
        current_state={},
        allowed_tools=["ai.extract"],
        planner_mode="deterministic",
    )

    assert result.verdict == Verdict.PASS
    assert llm.call_count == 1
    # And the prompt that went to the LLM included our proposal + the
    # ai.* contract explanation, so the model has the context it needs
    # to make the right call.
    rendered = llm.calls[0]["messages"][0]["content"]
    assert "ai.extract" in rendered
    assert "expected_schema" in rendered
    assert "OUTPUT" in rendered
    assert "Do NOT compare" in rendered


@pytest.mark.asyncio
async def test_verifier_still_replans_obvious_garbage_for_ai_ops():
    """The fix must NOT make the verifier blind to genuine quality
    issues — a placeholder instruction like 'x' with empty data should
    still surface (either REPLAN or FAIL) so demos with broken
    fixtures still fail loudly rather than silently producing
    nonsense."""
    # We let the LLM decide; here we mock REPLAN as the realistic
    # response to a clearly bogus proposal.
    replan_response = json.dumps(
        {
            "verdict": "replan",
            "reasoning": "Instruction 'x' is a placeholder and not meaningful",
            "issues": ["instruction is empty / placeholder"],
            "safety_flags": [],
            "suggestions": {"modifications": "Provide a concrete instruction"},
            "confidence": 0.85,
        }
    )
    llm = MockLLMPort(responses=[replan_response])
    critic = CriticAgent(llm_port=llm)

    bogus_proposal = {
        "tool": "ai.extract",
        "arguments": {
            "instruction": "x",
            "data": {},
            "expected_schema": {"type": "object", "required": ["something"]},
        },
    }
    result = await critic.verify_proposal(
        step=_ai_extract_step(),
        proposed_tool_call=bogus_proposal,
        run_id="run-verifier-bogus",
        completed_steps=[],
        current_state={},
    )
    # The verifier should still flag this — we just want it to flag
    # for the RIGHT reason (instruction is garbage), not for "data is
    # missing fields from expected_schema".
    assert result.verdict in (Verdict.REPLAN, Verdict.FAIL)
