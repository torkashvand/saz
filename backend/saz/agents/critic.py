"""Critic Agent - Pre-execution verifier and post-execution validator using LLM.

Provides two evaluation modes:
1. verify_proposal() - Pre-execution: evaluates a proposed tool call BEFORE execution
2. critique() - Post-execution: evaluates actual results AFTER execution
"""

import json
from typing import Any

import structlog

from .llm_port import LLMPort, LLMTransportError, get_llm_port
from .schemas import Critique, PlanStep, Verdict

logger = structlog.get_logger(__name__)


VERIFIER_SYSTEM_PROMPT = """You are a pre-execution safety verifier for the Saz workflow engine.

## Role
You evaluate a PROPOSED tool call BEFORE it executes.
You are the last gate before execution. The tool has NOT run yet.
Your verdict determines whether execution proceeds, is replanned, or is blocked.

## Evidence Available
You must base your verdict ONLY on the information below.
Do not assume information not provided. Do not infer external context.

### Step Details
- Step ID: {step_id}
- Step Type: {step_type}
- Tool: {tool_name}
- Step Intent: {step_reasoning}

### Proposed Tool Call
```json
{proposed_tool_call}
```

### Constraints
- Allowed tools: {allowed_tools}
- Planner mode: {planner_mode}

### Run Context
- Run ID: {run_id}
- Previous steps completed: {completed_steps}
- Current state: {current_state}

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
{{
  "verdict": "pass|fail|replan|escalate_to_human",
  "reasoning": "<your analysis referencing specific evidence from above>",
  "issues": ["<specific problems found, empty array if none>"],
  "safety_flags": ["<security/policy concerns, empty array if none>"],
  "suggestions": {{
    "next_action": "<what should happen next>",
    "modifications": "<if replan, what specifically should change>"
  }},
  "confidence": 0.0-1.0
}}"""  # noqa: E501


CRITIC_SYSTEM_PROMPT = """You are the post-execution critic for the Saz workflow engine.

## Role
Evaluate the ACTUAL RESULT of a tool execution and determine whether the step succeeded.
You must be rigorous on schema conformance but fair on content — small variations in
wording are acceptable if the data structure and required fields are correct.

## Evidence Available
Base your verdict ONLY on the evidence below.

### Step Details
- Step ID: {step_id}
- Step Type: {step_type}
- Tool: {tool_name}
- Step Intent: {step_reasoning}

### Expected Output Schema
```json
{expected_output_schema}
```

### Tool Call That Was Executed
```json
{tool_call}
```

### Actual Result
```json
{actual_result}
```

### Run Context
- Run ID: {run_id}
- Previous steps: {completed_steps}
- Current state: {current_state}

## Evaluation Checklist

Apply these checks in order of priority:

1. **Schema conformance** (most common failure mode):
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
{{
  "verdict": "pass|fail|replan|escalate_to_human",
  "reasoning": "<your analysis referencing specific schema fields and evidence>",
  "issues": ["<specific problems: name each wrong field, missing field, or type error>"],
  "safety_flags": ["<security/policy concerns, empty array if none>"],
  "suggestions": {{
    "next_action": "<what should happen next>",
    "modifications": "<if replan, what specifically should change in the instruction or approach>"
  }},
  "confidence": 0.0-1.0
}}"""  # noqa: E501


class CriticAgent:
    """LLM-powered pre-execution verifier and post-execution validator."""

    def __init__(self, model: str = "gpt-4o", llm_port: LLMPort | None = None):
        self.model = model
        self.llm_port = llm_port or get_llm_port()
        self.logger = logger.bind(agent="critic")

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

        prompt = VERIFIER_SYSTEM_PROMPT.format(
            step_id=step.step_id,
            step_type=step.step_type,
            tool_name=step.tool_name or "N/A",
            step_reasoning=step.reasoning,
            proposed_tool_call=json.dumps(proposed_tool_call, indent=2),
            allowed_tools=json.dumps(allowed_tools or []),
            planner_mode=planner_mode,
            run_id=run_id,
            completed_steps=json.dumps(completed_steps),
            current_state=json.dumps(current_state, default=str),
        )

        try:
            response = await self.llm_port.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": "Evaluate whether this proposed tool call is safe to execute.",
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )

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

        # Format prompt
        prompt = CRITIC_SYSTEM_PROMPT.format(
            step_id=step.step_id,
            step_type=step.step_type,
            tool_name=step.tool_name or "N/A",
            step_reasoning=step.reasoning,
            expected_output_schema=json.dumps(step.expected_output_schema, indent=2),
            tool_call=json.dumps(tool_call, indent=2),
            actual_result=json.dumps(result, indent=2, default=str),
            run_id=run_id,
            completed_steps=json.dumps(completed_steps),
            current_state=json.dumps(current_state, default=str),
        )

        # Call LLM with structured output
        try:
            response = await self.llm_port.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": "Evaluate the step execution and provide your critique.",
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.2,  # Slightly higher for nuanced evaluation
            )

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
