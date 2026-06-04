"""Regression tests for the post-execution critic on deterministic tool.call steps.

Context: deterministic `tool.call` and `artifact.*` steps carry NO declared
output contract — the planner always sets ``expected_output_schema = {}`` for
non-ai steps (see deterministic_planner.py). The critic prompt previously led
with "Schema conformance" and gave no guidance for an empty schema, so the LLM:

  * Read `### Expected Output Schema` as `{}`.
  * Interpreted `{}` as "no output is expected".
  * Saw the tool's real result fields (status, recap, artifact_id,
    stdout_preview, changed, ...) and called it a schema mismatch.
  * Returned verdict=fail, exhausting retries and failing the whole run —
    even though the ansible step itself executed cleanly (return_code=0).

This file pins the prompt-level fix so it cannot silently regress.
"""

from __future__ import annotations

import json

import pytest

from saz.agents.critic import CRITIC_SYSTEM_PROMPT, CriticAgent
from saz.agents.schemas import ErrorHandling, PlanStep, Verdict
from tests.conftest import MockLLMPort


def test_critic_prompt_explains_empty_schema_contract():
    """The critic prompt must explicitly tell the LLM that an empty expected
    output schema means NO declared contract — not "no output expected" — so
    it stops failing deterministic tool.call steps over their own result
    fields. If these strings disappear, the critic regresses to the broken
    behaviour that failed every deterministic tool step."""
    assert "Expected Output Schema" in CRITIC_SYSTEM_PROMPT
    # The empty-schema carve-out must be present and unambiguous.
    assert "{}" in CRITIC_SYSTEM_PROMPT
    assert "no declared output contract" in CRITIC_SYSTEM_PROMPT.lower()
    assert "tool.call" in CRITIC_SYSTEM_PROMPT
    # The two specific anti-patterns we depend on the LLM avoiding.
    assert 'no output expected' in CRITIC_SYSTEM_PROMPT.lower()
    assert "do not fail" in CRITIC_SYSTEM_PROMPT.lower()


def test_critic_prompt_has_no_format_braces():
    """The critic prompt is sent verbatim (no .format() is applied). It must
    NOT contain doubled `{{ }}` escaping — that would leak literal double
    braces to the model."""
    assert "{{" not in CRITIC_SYSTEM_PROMPT
    assert "}}" not in CRITIC_SYSTEM_PROMPT


def _ansible_step() -> PlanStep:
    """A deterministic tool.call step with no `expect` block, so the planner
    leaves expected_output_schema as the empty default `{}`."""
    return PlanStep(
        step_id="ansible_check",
        step_type="tool.call",
        tool_name="ansible_run",
        reasoning="Run the ansible check play and confirm it converges cleanly",
        error_handling=ErrorHandling.RETRY,
        max_retries=3,
    )


def _ansible_result() -> dict:
    """A realistic ansible_run result: real fields, no schema to match against."""
    return {
        "status": "success",
        "mode": "check",
        "recap": {"ok": 3, "changed": 2, "failed": 0, "unreachable": 0},
        "artifact_id": "art_abc123",
        "stdout_preview": "PLAY RECAP ... ok=3 changed=2 failed=0",
        "changed": True,
        "return_code": 0,
    }


@pytest.mark.asyncio
async def test_critic_passes_tool_call_with_empty_schema_and_result_fields():
    """End-to-end: a deterministic tool.call step with expected_output_schema
    == {} and a result full of tool-defined fields should NOT be failed on
    schema-conformance grounds. The fixed prompt gives the model the context
    to PASS; we verify the call renders cleanly and the verdict survives."""
    pass_response = json.dumps(
        {
            "verdict": "pass",
            "reasoning": (
                "Expected output schema is empty, so there is no declared output "
                "contract for this deterministic tool.call step. The ansible_run "
                "result reports return_code=0 and recap failed=0 — the step "
                "succeeded. Extra fields are tool-defined, not a violation."
            ),
            "issues": [],
            "safety_flags": [],
            "suggestions": {"next_action": "continue"},
            "confidence": 0.95,
        }
    )
    llm = MockLLMPort(responses=[pass_response])
    critic = CriticAgent(llm_port=llm)

    step = _ansible_step()
    # The exact value the planner produces for a non-ai step.
    assert step.expected_output_schema == {}

    result = await critic.critique(
        step=step,
        tool_call={"tool": "ansible_run", "arguments": {"playbook": "check.yml"}},
        result=_ansible_result(),
        run_id="run-critic-empty-schema",
        completed_steps=[],
        current_state={},
    )

    assert result.verdict == Verdict.PASS
    assert llm.call_count == 1

    # The system prompt that went to the LLM must carry the empty-schema
    # contract explanation, and the user message must carry the empty schema
    # plus the real result fields — together they give the model what it
    # needs to make the right call.
    system_msg = llm.calls[0]["messages"][0]["content"]
    user_msg = llm.calls[0]["messages"][1]["content"]
    assert "no declared output contract" in system_msg.lower()
    assert "Expected Output Schema" in user_msg
    assert "artifact_id" in user_msg
