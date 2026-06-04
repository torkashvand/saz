"""Prompt-cache hygiene: stable instructions live in the system message and
all per-run data lives in the user message.

These tests pin the message-bucket separation so a future edit cannot quietly
fold runtime values (run id, current data, budget, proposed tool call, actual
result, ...) back into the system prompt — which would defeat prompt caching
and mix stable instructions with this-run input.
"""

from __future__ import annotations

from saz.agents.agentic_planner import PLANNER_SYSTEM_PROMPT, _build_planner_user_message
from saz.agents.critic import (
    CRITIC_SYSTEM_PROMPT,
    VERIFIER_SYSTEM_PROMPT,
    _build_critic_user_message,
    _build_verifier_user_message,
)
from saz.agents.schemas import ErrorHandling, PlanStep

SECRET_VALUE = "tok-super-secret-ABC12345"


def _step() -> PlanStep:
    return PlanStep(
        step_id="route_incident",
        step_type="ai.route",
        tool_name="ai.route",
        reasoning="Pick the responding team",
        expected_output_schema={"type": "object", "required": ["route"]},
        error_handling=ErrorHandling.RETRY,
        max_retries=1,
    )


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


def test_planner_system_prompt_is_static_and_carries_no_run_data():
    """The planner system prompt must not contain any per-run values."""
    user_msg = _build_planner_user_message(
        workflow_spec={"name": "incident_triage", "steps": []},
        tool_registry=[{"name": "ai.route", "secret_token": SECRET_VALUE}],
        run_id="run-abc-123",
        completed_steps=["earlier_step"],
        current_data={"incident": "disk full"},
        budget={
            "remaining_tokens": 4242,
            "max_tokens": 100000,
            "remaining_cost": 1.5,
            "max_cost_usd": 10,
            "remaining_steps": 7,
            "max_steps": 50,
        },
    )

    # None of the volatile values may appear in the static system prompt.
    for needle in (
        "run-abc-123",
        "earlier_step",
        "disk full",
        "incident_triage",
        "4242",
        SECRET_VALUE,
    ):
        assert needle not in PLANNER_SYSTEM_PROMPT, f"{needle!r} leaked into system prompt"

    # And every one of them is present in the user message instead.
    for needle in ("run-abc-123", "earlier_step", "disk full", "incident_triage", "4242"):
        assert needle in user_msg, f"{needle!r} missing from user message"


def test_planner_user_message_has_data_sections_and_task_instruction():
    """The user message must carry the registry, spec, run context, and the
    concrete task instruction for this call."""
    user_msg = _build_planner_user_message(
        workflow_spec={"name": "wf", "steps": []},
        tool_registry=[{"name": "ai.route"}],
        run_id="run-1",
        completed_steps=[],
        current_data={},
        budget={},
    )

    assert "## Available Tools" in user_msg
    assert "## Workflow Specification" in user_msg
    assert "## Current Run Context" in user_msg
    assert "ai.route" in user_msg
    # The concrete task instruction now closes the user message, not a stub.
    assert user_msg.rstrip().endswith("Generate the execution plan JSON now.")


def test_planner_system_prompt_keeps_stable_rules():
    """Stable instruction blocks must remain in the system message."""
    assert "agentic workflow planner" in PLANNER_SYSTEM_PROMPT
    assert "Grounding Rules" in PLANNER_SYSTEM_PROMPT
    assert "Template Variable Syntax" in PLANNER_SYSTEM_PROMPT
    assert "Output Format" in PLANNER_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


def test_verifier_system_prompt_carries_no_run_data():
    """The verifier system prompt must hold only stable instructions."""
    proposed = {
        "tool": "ai.route",
        "arguments": {"instruction": "route", "token": SECRET_VALUE},
    }
    user_msg = _build_verifier_user_message(
        step=_step(),
        proposed_tool_call=proposed,
        run_id="run-xyz-999",
        completed_steps=["s0"],
        current_state={"s0": {"result": "ok"}},
        allowed_tools=["ai.route"],
        planner_mode="agentic",
    )

    for needle in ("run-xyz-999", "route_incident", SECRET_VALUE, "agentic"):
        assert needle not in VERIFIER_SYSTEM_PROMPT, f"{needle!r} leaked into system prompt"

    # The proposed tool call and run context belong to the user message.
    assert "Proposed Tool Call" in user_msg
    assert "run-xyz-999" in user_msg
    assert "route_incident" in user_msg
    assert "agentic" in user_msg
    assert SECRET_VALUE in user_msg  # carried verbatim where the caller put it
    assert user_msg.rstrip().endswith("safe to execute.")


def test_verifier_system_prompt_keeps_stable_rules():
    assert "pre-execution safety verifier" in VERIFIER_SYSTEM_PROMPT
    assert "Decision Policy" in VERIFIER_SYSTEM_PROMPT
    assert "Verdict Definitions" in VERIFIER_SYSTEM_PROMPT
    # The ai.* output-contract explanation must stay (regression guard).
    assert "Do NOT compare" in VERIFIER_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Critic
# ---------------------------------------------------------------------------


def test_critic_system_prompt_carries_no_run_data():
    """The critic system prompt must hold only stable instructions."""
    user_msg = _build_critic_user_message(
        step=_step(),
        tool_call={"tool": "ai.route", "arguments": {"token": SECRET_VALUE}},
        result={"route": "ops", "trace": SECRET_VALUE},
        run_id="run-crit-1",
        completed_steps=["s0"],
        current_state={"s0": {"ok": True}},
    )

    for needle in ("run-crit-1", "route_incident", SECRET_VALUE):
        assert needle not in CRITIC_SYSTEM_PROMPT, f"{needle!r} leaked into system prompt"

    # The actual result and run context belong to the user message.
    assert "Actual Result" in user_msg
    assert "run-crit-1" in user_msg
    assert "ops" in user_msg
    assert SECRET_VALUE in user_msg
    assert user_msg.rstrip().endswith("provide your critique.")


def test_critic_system_prompt_keeps_stable_rules():
    assert "post-execution critic" in CRITIC_SYSTEM_PROMPT
    assert "Evaluation Checklist" in CRITIC_SYSTEM_PROMPT
    assert "Schema conformance" in CRITIC_SYSTEM_PROMPT
    assert "Verdict Definitions" in CRITIC_SYSTEM_PROMPT
