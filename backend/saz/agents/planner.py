"""Planner Agent - Generates execution plans from workflow specifications using LLM."""
import json
import structlog
from typing import Dict, Any, List
from litellm import completion
from .schemas import ExecutionPlan, PlanStep, StepAction, ErrorHandling

logger = structlog.get_logger(__name__)


PLANNER_SYSTEM_PROMPT = """You are an autonomous workflow planner.

## Your Role
Generate a detailed, executable plan from a workflow specification. You have access to tools via an MCP-style registry. Your plan must be deterministic, auditable, and respect safety constraints.

## Available Tools
{tool_registry_json}

## Workflow Specification
```yaml
{workflow_spec}
```

## Current State
- Run ID: {run_id}
- Completed steps: {completed_steps}
- Current data: {current_data}
- Autonomy budget remaining:
  - Tokens: {remaining_tokens}/{max_tokens}
  - Cost: ${remaining_cost}/{max_cost_usd}
  - Steps: {remaining_steps}/{max_steps}

## Output Format
Generate a JSON execution plan with this EXACT structure:
{{
  "plan_id": "<uuid>",
  "steps": [
    {{
      "step_id": "<string matching workflow YAML>",
      "action": "tool_call",
      "tool_name": "<exact tool name from registry>",
      "input_template": {{"key": "{{{{variable}}}}"}},
      "expected_output_schema": {{"type": "object", "properties": {{}}}},
      "error_handling": "retry",
      "max_retries": 3,
      "reasoning": "<why this step>"
    }}
  ],
  "estimated_cost_usd": 0.0,
  "estimated_time_seconds": 0,
  "reasoning": "<overall plan justification>"
}}

## Critical Rules
- NEVER invent tools not in registry
- NEVER skip validation
- ALWAYS provide reasoning
- If unclear, use "human_approval" action
- Use {{{{variable}}}} syntax for templates

Generate the plan now."""


class PlannerAgent:
    """LLM-powered workflow planner"""

    def __init__(self, model: str = "gpt-4o"):
        self.model = model
        self.logger = logger.bind(agent="planner")

    async def plan(
        self,
        workflow_spec: Dict[str, Any],
        tool_registry: List[Dict],
        run_id: str,
        completed_steps: List[str],
        current_data: Dict,
        budget: Dict
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
            tools_count=len(tool_registry)
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
            max_steps=budget.get('max_steps', 50)
        )

        # Call LLM with structured output
        try:
            response = completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Generate the execution plan."}
                ],
                response_format={"type": "json_object"},
                temperature=0.1  # Low temperature for determinism
            )

            plan_json = json.loads(response.choices[0].message.content)

            # Validate with Pydantic
            plan = ExecutionPlan.model_validate(plan_json)

            self.logger.info(
                "plan_generated",
                plan_id=plan.plan_id,
                steps_count=len(plan.steps),
                estimated_cost=plan.estimated_cost_usd,
                estimated_time=plan.estimated_time_seconds,
                tokens_used=response.usage.total_tokens
            )

            return plan

        except Exception as e:
            self.logger.error("planning_failed", error=str(e))
            raise
