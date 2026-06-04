"""Critic Agent - Pre-execution verifier and post-execution validator using LLM.

Provides two evaluation modes:
1. verify_proposal() - Pre-execution: evaluates a proposed tool call BEFORE execution
2. critique() - Post-execution: evaluates actual results AFTER execution
"""

import json
from collections.abc import Callable
from typing import Any

import structlog

from .llm_port import LLMPort, LLMResponse, LLMTransportError, get_llm_port
from .schemas import Critique, PlanStep, Verdict

logger = structlog.get_logger(__name__)


# Stable verifier instructions. Sent verbatim on every call so it stays
# prompt-cache friendly — the per-run evidence (step details, proposed tool
# call, constraints, run context) is built into the user message by
# _build_verifier_user_message. Do not interpolate runtime values here.
VERIFIER_SYSTEM_PROMPT = """You are a pre-execution safety verifier for the Saz workflow engine.

## Role
You evaluate a PROPOSED tool call BEFORE it executes.
You are the last gate before execution. The tool has NOT run yet.
Your verdict determines whether execution proceeds, is replanned, or is blocked.

## Evidence Available
You must base your verdict ONLY on the evidence provided in the user message.
Do not assume information not provided. Do not infer external context.

## AI Operation Tool-Call Shape (READ FIRST)

For step types starting with `ai.` (ai.extract, ai.generate, ai.route, ai.assess, etc.) the
proposed tool call uses a specific contract you MUST understand before applying the checks:

- `instruction`: the prompt sent to the model.
- `data`: arbitrary context the model needs to do its job. Its shape is determined by the
  workflow author, NOT by the expected output. There is no required-keys list for `data`.
- `expected_schema`: the JSON Schema the model's OUTPUT must conform to (e.g.
  `properties.blast_radius`, `properties.ready_to_proceed`). These are the keys the
  *model will produce*, not keys the *call must contain*.

Therefore, for ai.* tool calls:

- Do NOT compare `expected_schema` property names against `data` keys.
- Do NOT say "data is missing X" when X is an `expected_schema` output property.
- Schema conformance of the OUTPUT is enforced by the AI op runtime (validation +
  ai.fix_json repair) and by the post-execution critic. It is NOT your responsibility
  to verify that the model will produce all required output fields.

For non-ai tools (http_request, ansible_run, webhook_emit, artifact.store, ...) the tool
call must contain all arguments declared as required by the tool's input schema, and you
SHOULD flag missing required arguments.

## Decision Policy

Apply these checks in order:

1. **Tool validity**: Is the tool in the allowed tool set? If not → FAIL.
2. **Required arguments** (non-ai tools only): Does the tool call include all required
   arguments for the tool's own input schema? If critical arguments are missing → REPLAN.
   For ai.* tools, treat `instruction` as the only hard requirement; `data` and
   `expected_schema` are workflow-author concerns, not yours.
3. **Intent alignment**: Does the tool call accomplish what the step intent describes? If
   fundamentally misaligned (e.g. the instruction is empty / placeholder / nonsense, or the
   tool is the wrong one for the intent) → FAIL.
4. **Safety**: Could this call cause data loss, unauthorized access, or destructive side
   effects without safeguards? If yes → FAIL or ESCALATE.
5. **Credential usage**: Are secrets/credentials used appropriately? If credentials are
   exposed in plain text or sent to wrong endpoints → FAIL.
6. **Completeness**: Are arguments reasonable and well-formed? If fixable → REPLAN. If
   reasonable → PASS. Do not REPLAN over output-contract concerns for ai.* tools — those
   are not fixable at this stage.

## Verdict Definitions
- **pass**: Safe, aligned with intent, arguments are complete and reasonable.
- **fail**: Unsafe, wrong tool, would cause harm, or fundamentally misaligned. Cannot be fixed by replanning.
- **replan**: The objective is valid but the call is malformed, missing arguments, or uses a suboptimal approach. A revised plan could fix this.
- **escalate_to_human**: The operation is materially risky (e.g., production deployment, financial transaction, bulk data modification) and cannot be verified as safe from available evidence alone.

## Output Format
Return ONLY this JSON structure:
{
  "verdict": "pass|fail|replan|escalate_to_human",
  "reasoning": "<your analysis referencing specific evidence from above>",
  "issues": ["<specific problems found, empty array if none>"],
  "safety_flags": ["<security/policy concerns, empty array if none>"],
  "suggestions": {
    "next_action": "<what should happen next>",
    "modifications": "<if replan, what specifically should change>"
  },
  "confidence": 0.0-1.0
}"""  # noqa: E501


# Stable critic instructions. Sent verbatim on every call so it stays
# prompt-cache friendly — the per-run evidence (step details, expected schema,
# executed tool call, actual result, run context) is built into the user
# message by _build_critic_user_message. Do not interpolate runtime values here.
CRITIC_SYSTEM_PROMPT = """You are the post-execution critic for the Saz workflow engine.

## Role
Evaluate the ACTUAL RESULT of a tool execution and determine whether the step succeeded.
You must be rigorous on schema conformance but fair on content — small variations in
wording are acceptable if the data structure and required fields are correct.

## Evidence Available
Base your verdict ONLY on the evidence provided in the user message.

## Expected Output Schema Contract (READ FIRST)

The `### Expected Output Schema` block carries the step's declared OUTPUT contract.
Decide which case you are in BEFORE applying the checklist:

- If the schema declares properties and/or required fields (a real contract), enforce
  schema conformance strictly, exactly as described in check 1.
- If the schema is EMPTY ({}) or otherwise declares no properties and no required
  fields, the step has NO declared output contract. This is normal and expected for
  deterministic `tool.call` and `artifact.*` steps, whose result shape is defined by
  the tool itself, not by the workflow author. In that case:
  - Do NOT treat an empty schema as "no output expected."
  - Do NOT FAIL because the actual result contains fields (e.g. status, mode, recap,
    artifact_id, stdout_preview, changed). Extra fields are expected, not a violation.
  - Skip schema conformance entirely (check 1 does not apply) and judge the step on
    content quality and safety: did the tool succeed, are there error/partial-failure
    signals (non-zero return codes, failed counts, error fields), is the data unsafe.

## Evaluation Checklist

Apply these checks in order of priority:

1. **Schema conformance** (only when a contract is declared — see above):
   - Do the JSON keys in the result EXACTLY match the expected schema property names?
   - Are all required fields present?
   - Are field types correct (string vs number vs boolean vs array)?
   - Are enum constraints satisfied (if the schema specifies allowed values)?
   - Common failure: the model uses human-readable key names (e.g., "Category")
     instead of the schema-specified keys (e.g., "category"). This is a FAIL.

2. **Content quality**:
   - Does the result answer the step's intent?
   - Is the data plausible given the input?
   - Are there obvious hallucinations (data not derivable from the input)?

3. **Safety**:
   - Does the result contain PII that should be redacted?
   - Does the result violate security policies?
   - Is there evidence of tool-level errors or partial failures?

## Verdict Definitions
- **pass**: Output matches the expected schema, required fields are present with correct types, content addresses the step intent. Minor wording variations are acceptable.
- **fail**: Output does not match schema (wrong keys, missing required fields, wrong types, invalid enum values), or contains safety violations. Retrying with the same approach will likely produce the same error.
- **replan**: Tool executed but the result is incomplete or the approach needs adjustment. A different tool configuration or instruction could fix it.
- **escalate_to_human**: The result is ambiguous or the operation has consequences that require human judgment.

## Output Format
Return ONLY this JSON structure:
{
  "verdict": "pass|fail|replan|escalate_to_human",
  "reasoning": "<your analysis referencing specific schema fields and evidence>",
  "issues": ["<specific problems: name each wrong field, missing field, or type error>"],
  "safety_flags": ["<security/policy concerns, empty array if none>"],
  "suggestions": {
    "next_action": "<what should happen next>",
    "modifications": "<if replan, what specifically should change in the instruction or approach>"
  },
  "confidence": 0.0-1.0
}"""  # noqa: E501


def _build_verifier_user_message(
    step: PlanStep,
    proposed_tool_call: dict[str, Any],
    run_id: str,
    completed_steps: list[str],
    current_state: dict[str, Any],
    allowed_tools: list[str] | None,
    planner_mode: str,
) -> str:
    """Assemble the per-run evidence message for the pre-execution verifier.

    Carries the runtime-specific evidence (step details, proposed tool call,
    constraints, run context) so the system prompt stays static and cacheable.
    Ends with the concrete task instruction for this call.
    """
    return (
        "### Step Details\n"
        f"- Step ID: {step.step_id}\n"
        f"- Step Type: {step.step_type}\n"
        f"- Tool: {step.tool_name or 'N/A'}\n"
        f"- Step Intent: {step.reasoning}\n"
        "\n"
        "### Proposed Tool Call\n"
        "```json\n"
        f"{json.dumps(proposed_tool_call, indent=2)}\n"
        "```\n"
        "\n"
        "### Constraints\n"
        f"- Allowed tools: {json.dumps(allowed_tools or [])}\n"
        f"- Planner mode: {planner_mode}\n"
        "\n"
        "### Run Context\n"
        f"- Run ID: {run_id}\n"
        f"- Previous steps completed: {json.dumps(completed_steps)}\n"
        f"- Current state: {json.dumps(current_state, default=str)}\n"
        "\n"
        "Evaluate whether this proposed tool call is safe to execute."
    )


def _build_critic_user_message(
    step: PlanStep,
    tool_call: dict[str, Any],
    result: dict[str, Any],
    run_id: str,
    completed_steps: list[str],
    current_state: dict[str, Any],
) -> str:
    """Assemble the per-run evidence message for the post-execution critic.

    Carries the runtime-specific evidence (step details, expected schema,
    executed tool call, actual result, run context) so the system prompt stays
    static and cacheable. Ends with the concrete task instruction for this call.
    """
    return (
        "### Step Details\n"
        f"- Step ID: {step.step_id}\n"
        f"- Step Type: {step.step_type}\n"
        f"- Tool: {step.tool_name or 'N/A'}\n"
        f"- Step Intent: {step.reasoning}\n"
        "\n"
        "### Expected Output Schema\n"
        "```json\n"
        f"{json.dumps(step.expected_output_schema, indent=2)}\n"
        "```\n"
        "\n"
        "### Tool Call That Was Executed\n"
        "```json\n"
        f"{json.dumps(tool_call, indent=2)}\n"
        "```\n"
        "\n"
        "### Actual Result\n"
        "```json\n"
        f"{json.dumps(result, indent=2, default=str)}\n"
        "```\n"
        "\n"
        "### Run Context\n"
        f"- Run ID: {run_id}\n"
        f"- Previous steps: {json.dumps(completed_steps)}\n"
        f"- Current state: {json.dumps(current_state, default=str)}\n"
        "\n"
        "Evaluate the step execution and provide your critique."
    )


class CriticAgent:
    """LLM-powered pre-execution verifier and post-execution validator."""

    def __init__(self, model: str = "gpt-4o", llm_port: LLMPort | None = None):
        self.model = model
        self.llm_port = llm_port or get_llm_port()
        self.logger = logger.bind(agent="critic")
        # Set by the executor wiring so verifier/critic LLM spend counts
        # toward the run budget. Signature: (run_id, tokens, cost_usd).
        self.usage_recorder: Callable[[str, int, float], None] | None = None

    def _record_usage(self, run_id: str, response: LLMResponse) -> None:
        if self.usage_recorder is not None:
            self.usage_recorder(run_id, response.total_tokens, response.cost_usd)

    async def verify_proposal(
        self,
        step: PlanStep,
        proposed_tool_call: dict[str, Any],
        run_id: str,
        completed_steps: list[str],
        current_state: dict[str, Any],
        allowed_tools: list[str] | None = None,
        planner_mode: str = "deterministic",
    ) -> Critique:
        """
        Pre-execution verification: evaluate a proposed tool call BEFORE execution.

        This is the safety gate that ensures only approved actions execute.

        Args:
            step: Plan step being verified
            proposed_tool_call: Tool call that would be executed
            run_id: Current run identifier
            completed_steps: List of completed step IDs
            current_state: Current workflow state
            allowed_tools: List of allowed tool names
            planner_mode: Current planning mode

        Returns:
            Critique with verdict (pass/fail/replan/escalate)
        """
        self.logger.info(
            "verifying_proposal",
            step_id=step.step_id,
            tool=proposed_tool_call.get("tool"),
            run_id=run_id,
        )

        user_message = _build_verifier_user_message(
            step=step,
            proposed_tool_call=proposed_tool_call,
            run_id=run_id,
            completed_steps=completed_steps,
            current_state=current_state,
            allowed_tools=allowed_tools,
            planner_mode=planner_mode,
        )

        try:
            response = await self.llm_port.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            self._record_usage(run_id, response)

            verdict_json = json.loads(response.content)
            critique = Critique.model_validate(verdict_json)

            self.logger.info(
                "verification_complete",
                step_id=step.step_id,
                verdict=critique.verdict.value,
                confidence=critique.confidence,
                safety_flags_count=len(critique.safety_flags),
                tokens_used=response.total_tokens,
            )

            if critique.safety_flags:
                self.logger.warning(
                    "pre_execution_safety_flags",
                    step_id=step.step_id,
                    flags=critique.safety_flags,
                )

            return critique

        except LLMTransportError:
            # The model never produced a verdict — provider was unreachable
            # (rate-limited, auth failure, network issue). Don't bucket this
            # into the human-approval queue: it's a run failure, not a
            # decision. Let the executor surface it as a structured run
            # error so retry/backoff and operator visibility work normally.
            self.logger.error(
                "verifier_transport_failure",
                step_id=step.step_id,
                phase="pre_execution",
            )
            raise
        except Exception as e:
            self.logger.error("verification_failed", error=str(e), step_id=step.step_id)
            return Critique(
                verdict=Verdict.ESCALATE,
                reasoning=f"Pre-execution verification failed: {str(e)}",
                issues=[f"Verifier error: {str(e)}"],
                safety_flags=["verifier_failure"],
                suggestions={
                    "next_action": "escalate_to_human",
                    "reason": "Automatic verification failed",
                },
                confidence=0.0,
            )

    async def critique(
        self,
        step: PlanStep,
        tool_call: dict[str, Any],
        result: dict[str, Any],
        run_id: str,
        completed_steps: list[str],
        current_state: dict[str, Any],
    ) -> Critique:
        """
        Evaluate a step execution result.

        Args:
            step: Original plan step
            tool_call: Tool call that was executed
            result: Actual result from tool execution
            run_id: Current run identifier
            completed_steps: List of completed step IDs
            current_state: Current workflow state

        Returns:
            Critique with verdict and recommendations
        """
        self.logger.info(
            "critiquing_step", step_id=step.step_id, tool=step.tool_name, run_id=run_id
        )

        user_message = _build_critic_user_message(
            step=step,
            tool_call=tool_call,
            result=result,
            run_id=run_id,
            completed_steps=completed_steps,
            current_state=current_state,
        )

        # Call LLM with structured output
        try:
            response = await self.llm_port.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,  # Slightly higher for nuanced evaluation
            )
            self._record_usage(run_id, response)

            critique_json = json.loads(response.content)

            # Validate with Pydantic
            critique = Critique.model_validate(critique_json)

            self.logger.info(
                "critique_generated",
                step_id=step.step_id,
                verdict=critique.verdict.value,
                confidence=critique.confidence,
                issues_count=len(critique.issues),
                safety_flags_count=len(critique.safety_flags),
                tokens_used=response.total_tokens,
            )

            # Log warnings for safety flags
            if critique.safety_flags:
                self.logger.warning(
                    "safety_flags_detected", step_id=step.step_id, flags=critique.safety_flags
                )

            return critique

        except LLMTransportError:
            # Provider unreachable — see verify_pre_execution for rationale.
            self.logger.error(
                "verifier_transport_failure",
                step_id=step.step_id,
                phase="post_execution",
            )
            raise
        except Exception as e:
            self.logger.error("critique_failed", error=str(e), step_id=step.step_id)
            # Return defensive critique on error
            return Critique(
                verdict=Verdict.ESCALATE,
                reasoning=f"Critique failed due to error: {str(e)}",
                issues=[f"Critic error: {str(e)}"],
                safety_flags=["critic_failure"],
                suggestions={
                    "next_action": "escalate_to_human",
                    "reason": "Automatic evaluation failed",
                },
                confidence=0.0,
            )
