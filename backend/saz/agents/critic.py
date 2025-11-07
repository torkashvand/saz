"""Critic Agent - Validates step execution results and decides next action using LLM."""

import json
from typing import Any

import structlog

from .llm_port import LLMPort, get_llm_port
from .schemas import Critique, PlanStep, Verdict

logger = structlog.get_logger(__name__)


CRITIC_SYSTEM_PROMPT = """You are an autonomous workflow critic and validator.

## Your Role
Evaluate the result of a workflow step execution and determine if it succeeded, failed, or requires
replanning. You must be rigorous but fair - small variations are acceptable if the core objective
was met.

## Step Details
Step ID: {step_id}
Action: {action}
Tool: {tool_name}
Reasoning: {step_reasoning}

## Expected Output Schema
```json
{expected_output_schema}
```

## Tool Call
```json
{tool_call}
```

## Actual Result
```json
{actual_result}
```

## Context
- Run ID: {run_id}
- Previous steps: {completed_steps}
- Current workflow state: {current_state}

## Safety Checks
- Does the result contain PII that should be redacted?
- Does the result violate any security policies?
- Does the result match the expected schema?
- Is there evidence of errors or partial failures?

## Output Format
Generate a JSON critique with this EXACT structure:
{{
  "verdict": "pass|fail|replan|escalate_to_human",
  "reasoning": "<detailed analysis of why this verdict>",
  "issues": ["<list of problems found, empty array if none>"],
  "safety_flags": ["<security/policy concerns, empty array if none>"],
  "suggestions": {{
    "next_action": "<what should happen next>",
    "modifications": "<if replan, what should change>"
  }},
  "confidence": 0.0-1.0
}}

## Verdict Guidelines
- **pass**: Step succeeded, output matches schema, no safety issues
- **fail**: Unrecoverable error, invalid output, or safety violation
- **replan**: Step partially succeeded but needs a different approach
- **escalate_to_human**: Ambiguous result requiring human judgment

Generate the critique now."""


class CriticAgent:
    """LLM-powered step result validator"""

    def __init__(self, model: str = "gpt-4o", llm_port: LLMPort | None = None):
        self.model = model
        self.llm_port = llm_port or get_llm_port()
        self.logger = logger.bind(agent="critic")

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
            action=step.action.value,
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
