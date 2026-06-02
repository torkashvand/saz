"""Planner and critic LLM spend must count toward the run budget."""

import json

import pytest

from saz.agents.critic import CriticAgent
from saz.agents.llm_port import LLMPort, LLMResponse
from saz.agents.schemas import PlanStep
from saz.policies.policy_engine import PolicyEngine

_PASS_CRITIQUE = json.dumps(
    {
        "verdict": "pass",
        "reasoning": "ok",
        "issues": [],
        "safety_flags": [],
        "suggestions": {},
        "confidence": 0.9,
    }
)


class _CostingLLM(LLMPort):
    """Returns a fixed critique with known token + cost usage."""

    def __init__(self, tokens: int, cost_usd: float) -> None:
        self.tokens = tokens
        self.cost_usd = cost_usd

    async def complete(self, **kwargs) -> LLMResponse:  # type: ignore[override]
        return LLMResponse(
            content=_PASS_CRITIQUE,
            total_tokens=self.tokens,
            cost_usd=self.cost_usd,
            model="fake",
        )


@pytest.mark.asyncio
async def test_critic_usage_is_recorded_against_budget() -> None:
    engine = PolicyEngine()
    engine.initialize_run("run-1")

    critic = CriticAgent(llm_port=_CostingLLM(tokens=750, cost_usd=0.03))
    critic.usage_recorder = engine.record_llm_usage

    before = engine.get_budget_status("run-1")
    await critic.verify_proposal(
        step=PlanStep(step_id="s1", step_type="tool.call", reasoning="r"),
        proposed_tool_call={"tool": "http_request", "arguments": {}},
        run_id="run-1",
        completed_steps=[],
        current_state={},
    )
    after = engine.get_budget_status("run-1")

    assert after["tokens"]["used"] == before["tokens"]["used"] + 750
    assert after["cost"]["used"] == pytest.approx(before["cost"]["used"] + 0.03)


@pytest.mark.asyncio
async def test_critic_without_recorder_does_not_crash() -> None:
    critic = CriticAgent(llm_port=_CostingLLM(tokens=10, cost_usd=0.0))
    # No usage_recorder wired — must still return a verdict.
    verdict = await critic.verify_proposal(
        step=PlanStep(step_id="s1", step_type="tool.call", reasoning="r"),
        proposed_tool_call={"tool": "http_request", "arguments": {}},
        run_id="run-x",
        completed_steps=[],
        current_state={},
    )
    assert verdict.verdict.value == "pass"


def test_executor_wires_usage_recorder_onto_critic_and_planner() -> None:
    from unittest.mock import MagicMock

    from saz.agents.agentic_planner import AgenticPlanner
    from saz.engine.executor import WorkflowExecutor

    engine = PolicyEngine()
    critic = CriticAgent(llm_port=_CostingLLM(tokens=1, cost_usd=0.0))
    planner = AgenticPlanner(llm_port=_CostingLLM(tokens=1, cost_usd=0.0))

    WorkflowExecutor(
        uow=MagicMock(),
        tool_registry=MagicMock(),
        planner=planner,
        executor_agent=MagicMock(),
        critic=critic,
        policy_engine=engine,
    )

    assert critic.usage_recorder == engine.record_llm_usage
    assert planner.usage_recorder == engine.record_llm_usage
