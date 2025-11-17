"""Planner Agent - Generates execution plans from workflow specifications using LLM."""

import json
from typing import Any

import structlog

from .llm_port import LLMPort, get_llm_port
from .schemas import ExecutionPlan

logger = structlog.get_logger(__name__)


PLANNER_SYSTEM_PROMPT = """You are the **agentic workflow planner** for Saz.

You are only used when:

- `workflow.planner_mode == "agentic"`

---

## Role

Given:

- A workflow specification (Saz DSL)
- An MCP-style tool registry
- Current run state and autonomy budget

Generate a **detailed ExecutionPlan JSON** for this run.

The plan must be:

- Deterministic for the same inputs
- Auditable and easy to understand
- Respectful of safety constraints and budgets

---

## Available Tools

These are the tools you may call:

```json
{tool_registry_json}
```

You must **only** use tools from this registry.

---

## Workflow Specification

This is the human-authored DSL definition of the flow:

```yaml
{workflow_spec}
```

Semantics:

- If `workflow.steps` is **present and non-empty**:
  - Treat them as **structural hints and human intent**, not a strict graph.
  - You MAY:
    - Insert extra validation / guard / routing steps
    - Merge simple steps
  - Prefer to keep the overall order unless reordering is clearly beneficial.
- If `workflow.steps` is **empty**:
  - Derive the entire plan from:
    - `flow.description`
    - `form` fields
    - `triggers`
    - Available tools

---

## Current State

```text
Run ID: {run_id}
Completed steps: {completed_steps}
Current data: {current_data}

Autonomy budget remaining:
- Tokens: {remaining_tokens}/{max_tokens}
- Cost: ${remaining_cost}/{max_cost_usd}
- Steps: {remaining_steps}/{max_steps}
```

Use the budget wisely. Prefer shorter, effective plans over long chains of marginal steps.

---

## Output Format

Return a **single JSON object** with this shape:

```jsonc
{
  "plan_id": "<uuid>",
  "steps": [
    {
      "step_id": "<short snake_case id>",
      "action": "tool_call",
      "tool_name": "<exact tool name from registry>",
      "input_template": {
        // JSON object. Values are template strings like:
        // "{{ $form.field_name }}" or "{{ $step('previous_step').field }}"
        // or "{{ $env('VAR_NAME') }}", "{{ $secret('NAME') }}"
      },
      "expected_output_schema": {
        "type": "object",
        "properties": {}
      },
      "error_handling": "retry",
      "max_retries": 3,
      "reasoning": "<why this step exists, what it does, and how it uses its inputs>"
    }
  ],
  "estimated_cost_usd": 0.0,
  "estimated_time_seconds": 0,
  "reasoning": "<overall plan justification and high-level strategy>"
}
```

Notes:

- If the DSL already defines step ids, **reuse them when appropriate**.
- For any additional steps you introduce, invent **clear, meaningful** ids.

---

## Valid `error_handling` Values

`error_handling` MUST be **one** of:

- `"retry"`     – Retry on transient failures.
- `"fail"`      – Fail the whole workflow on error.
- `"escalate"`  – Stop and require human intervention.
- `"continue"`  – Log error but continue with next steps.

Do **not** use any other values.

---

## Template Variable Syntax

You are generating **templates**, not concrete values.

- Form data:
  `{{ $form.field_name }}`
- Previous step results:
  `{{ $step('step_id').field }}`
  or `{{ $step('step_id') }}` for the full output object
  > `"$step()" already returns the output; do **not** use `.output.field`.
- Environment variables:
  `{{ $env('VAR_NAME') }}`
- Secrets:
  `{{ $secret('SECRET_NAME') }}`

Make sure templates line up with what each tool expects as input.

---

## Planning Guidelines

- **Align with human intent** in the DSL:
  - Respect the flow’s `description`, `form`, and any existing `workflow.steps`.
  - Do not fight the intent; extend and guard it.
- **Be conservative with tools**:
  - Use the smallest number of tools needed to achieve the goal.
  - Avoid redundant or obviously useless calls.
- **Add value with structure**:
  - You can add pre-checks, validations, routing, or post-verification steps when helpful.
  - You can split a big risky action into “plan → validate → execute” if it improves safety.

---

## Critical Rules

- NEVER invent tools that are not present in the registry.
- NEVER skip basic validation when dealing with external side effects.
- ALWAYS provide:
  - A global `reasoning` field for the plan.
  - A `reasoning` field for each step.
- Respect the autonomy budget (tokens, cost, steps).
- Prefer clear, auditable data flows using `$form`, `$step`, `$env`, and `$secret` templates exactly as specified.

---

Generate the **execution plan JSON** now.
"""  # noqa: E501


class PlannerAgent:
    """LLM-powered workflow planner"""

    def __init__(self, model: str = "gpt-4o", llm_port: LLMPort | None = None):
        self.model = model
        self.llm_port = llm_port or get_llm_port()
        self.logger = logger.bind(agent="planner")

    async def plan(
        self,
        workflow_spec: dict[str, Any],
        tool_registry: list[dict],
        run_id: str,
        completed_steps: list[str],
        current_data: dict,
        budget: dict,
    ) -> ExecutionPlan:
        """
        Generate execution plan from workflow spec.

        Args:
            workflow_spec: Parsed YAML workflow
            tool_registry: Available tools (MCP schema format)
            run_id: Current run identifier
            completed_steps: Already executed step IDs
            current_data: Available context data
            budget: Remaining autonomy budget

        Returns:
            ExecutionPlan with validated structure
        """
        import yaml

        self.logger.info(
            "planning_workflow",
            workflow=workflow_spec.get('name'),
            run_id=run_id,
            tools_count=len(tool_registry),
        )

        # Format prompt
        prompt = PLANNER_SYSTEM_PROMPT.format(
            tool_registry_json=json.dumps(tool_registry, indent=2),
            workflow_spec=yaml.dump(workflow_spec),
            run_id=run_id,
            completed_steps=json.dumps(completed_steps),
            current_data=json.dumps(current_data, default=str),
            remaining_tokens=budget.get('remaining_tokens', 0),
            max_tokens=budget.get('max_tokens', 100000),
            remaining_cost=budget.get('remaining_cost', 0),
            max_cost_usd=budget.get('max_cost_usd', 10),
            remaining_steps=budget.get('remaining_steps', 0),
            max_steps=budget.get('max_steps', 50),
        )

        # Call LLM with structured output
        try:
            response = await self.llm_port.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Generate the execution plan."},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,  # Low temperature for determinism
            )

            plan_json = json.loads(response.content)

            # Validate with Pydantic
            plan = ExecutionPlan.model_validate(plan_json)

            self.logger.info(
                "plan_generated",
                plan_id=plan.plan_id,
                steps_count=len(plan.steps),
                estimated_cost=plan.estimated_cost_usd,
                estimated_time=plan.estimated_time_seconds,
                tokens_used=response.total_tokens,
            )

            return plan

        except Exception as e:
            self.logger.error("planning_failed", error=str(e))
            raise
