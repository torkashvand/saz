"""Verifier must not bucket LLM transport failures as ESCALATE.

A rate-limit / auth / network failure from the model provider means the
model never weighed in — it is a run failure, not a deliberate "this needs
a human" verdict. Putting transport errors in the human-approval queue
silently parks broken runs as "Awaiting Approval", which is what the bug
report showed.

Other exceptions (parse failures, unexpected runtime errors) still fall
back to ESCALATE — safety-by-default, since those COULD represent a
real model output we just can't interpret.
"""

from __future__ import annotations

import pytest

from saz.agents.critic import CriticAgent
from saz.agents.llm_port import LLMPort, LLMResponse, LLMTransportError
from saz.agents.schemas import PlanStep, Verdict


class _RaisingPort(LLMPort):
    def __init__(self, exc: Exception):
        self.exc = exc

    async def complete(self, *args, **kwargs) -> LLMResponse:  # type: ignore[override]
        raise self.exc


def _step() -> PlanStep:
    return PlanStep(
        step_id="s1",
        step_type="tool.call",
        tool_name="http_request",
        reasoning="test step",
    )


@pytest.mark.asyncio
async def test_pre_execution_propagates_transport_error() -> None:
    """Pre-execution: an LLMTransportError from the verifier call must
    propagate as a transport error, NOT become a Critique(ESCALATE)."""

    agent = CriticAgent(llm_port=_RaisingPort(LLMTransportError("rate limit")))
    with pytest.raises(LLMTransportError):
        await agent.verify_proposal(
            step=_step(),
            proposed_tool_call={"tool": "http_request", "arguments": {}},
            run_id="r1",
            completed_steps=[],
            current_state={},
            allowed_tools=["http_request"],
            planner_mode="deterministic",
        )


@pytest.mark.asyncio
async def test_pre_execution_other_exceptions_still_escalate() -> None:
    """A non-transport exception (parse error, unexpected runtime issue)
    still falls back to Critique(ESCALATE) — safety by default."""

    agent = CriticAgent(llm_port=_RaisingPort(ValueError("malformed JSON")))
    result = await agent.verify_proposal(
        step=_step(),
        proposed_tool_call={"tool": "http_request", "arguments": {}},
        run_id="r1",
        completed_steps=[],
        current_state={},
        allowed_tools=["http_request"],
        planner_mode="deterministic",
    )
    assert result.verdict == Verdict.ESCALATE
    assert "verifier_failure" in result.safety_flags


@pytest.mark.asyncio
async def test_post_execution_propagates_transport_error() -> None:
    """Same contract for the post-execution critique path."""

    agent = CriticAgent(llm_port=_RaisingPort(LLMTransportError("auth")))
    with pytest.raises(LLMTransportError):
        await agent.critique(
            step=_step(),
            tool_call={"tool": "http_request", "arguments": {}},
            result={"output": {}},
            run_id="r1",
            completed_steps=[],
            current_state={},
        )


@pytest.mark.asyncio
async def test_post_execution_other_exceptions_still_escalate() -> None:
    agent = CriticAgent(llm_port=_RaisingPort(RuntimeError("oops")))
    result = await agent.critique(
        step=_step(),
        tool_call={"tool": "http_request", "arguments": {}},
        result={"output": {}},
        run_id="r1",
        completed_steps=[],
        current_state={},
    )
    assert result.verdict == Verdict.ESCALATE
    assert "critic_failure" in result.safety_flags
