"""Step Planner - Deterministic YAML→Plan converter.

For workflows with explicit steps, converts workflow.steps directly to ExecutionPlan
without LLM calls. This provides fast, cost-free ($0), predictable execution.

LLMs are still used INSIDE ai.* step types (ai.extract, ai.generate, etc.) but not
for planning the overall workflow graph.
"""

from typing import Any
from uuid import uuid4

import structlog

from .schemas import ErrorHandling, ExecutionPlan, PlanStep, StepAction

logger = structlog.get_logger(__name__)


class DeterministicPlanner:
    """Deterministic planner - converts YAML steps to ExecutionPlan without LLM."""

    def __init__(self) -> None:
        """Initialize step planner."""
        self.logger = logger.bind(agent="step_planner")

        # Map DSL step types to StepAction enum
        self._action_map: dict[str, StepAction] = {
            "tool.call": StepAction.TOOL_CALL,
            "condition": StepAction.CONDITION,
            "human.approval": StepAction.HUMAN_APPROVAL,
            "webhook.wait": StepAction.WEBHOOK_WAIT,
            # AI ops are all treated as TOOL_CALL (they're registered as MCP tools)
            "ai.extract": StepAction.TOOL_CALL,
            "ai.generate": StepAction.TOOL_CALL,
            "ai.route": StepAction.TOOL_CALL,
            "ai.score": StepAction.TOOL_CALL,
            "ai.assess": StepAction.TOOL_CALL,
            "ai.normalize": StepAction.TOOL_CALL,
            "ai.match": StepAction.TOOL_CALL,
            "ai.evaluate": StepAction.TOOL_CALL,
            "ai.compare": StepAction.TOOL_CALL,
            "ai.translate": StepAction.TOOL_CALL,
            "ai.summarize": StepAction.TOOL_CALL,
            "ai.fix_json": StepAction.TOOL_CALL,
            "artifact.store": StepAction.TOOL_CALL,
            "artifact.retrieve": StepAction.TOOL_CALL,
        }

    async def plan(
        self,
        workflow_spec: dict[str, Any],
        tool_registry: list[dict[str, Any]],
        run_id: str,
        completed_steps: list[str],
        current_data: dict[str, Any],
        budget: dict[str, Any],
    ) -> ExecutionPlan:
        """
        Generate deterministic execution plan from explicit workflow steps.

        Args:
            workflow_spec: Workflow specification with steps
            tool_registry: Available tools (for validation)
            run_id: Run identifier
            completed_steps: Already completed step IDs
            current_data: Execution context
            budget: Budget constraints

        Returns:
            ExecutionPlan with steps converted 1:1 from YAML
        """
        steps_spec: list[dict[str, Any]] = list(workflow_spec.get("steps", []))

        self.logger.info(
            "planning_workflow_deterministic",
            workflow=workflow_spec.get("name"),
            run_id=run_id,
            steps_total=len(steps_spec),
            mode="deterministic",
        )

        # Filter out already-completed steps
        remaining_steps = [s for s in steps_spec if s.get("id") not in completed_steps]

        # Convert each YAML step to PlanStep
        plan_steps: list[PlanStep] = []
        for step_dict in remaining_steps:
            plan_step = self._convert_step(step_dict, tool_registry)
            plan_steps.append(plan_step)

        # Build execution plan
        plan = ExecutionPlan(
            plan_id=str(uuid4()),
            steps=plan_steps,
            estimated_cost_usd=0.0,  # No planning cost (deterministic)
            estimated_time_seconds=len(plan_steps) * 5,  # Rough estimate
            reasoning=f"Deterministic execution of {len(plan_steps)} explicit workflow steps",
        )

        self.logger.info(
            "plan_generated_deterministic",
            plan_id=plan.plan_id,
            steps_count=len(plan_steps),
            cost=0.0,
        )

        return plan

    def _convert_step(
        self, step_dict: dict[str, Any], tool_registry: list[dict[str, Any]]
    ) -> PlanStep:
        """
        Convert a single YAML step to PlanStep.

        Args:
            step_dict: Step from workflow.steps
            tool_registry: Available tools for validation

        Returns:
            PlanStep ready for execution
        """
        step_id = step_dict["id"]
        step_type = step_dict["type"]

        # Map type to action
        action = self._action_map.get(step_type, StepAction.TOOL_CALL)

        # Determine tool name
        tool_name = self._get_tool_name(step_dict, step_type)

        # Build input template
        input_template = self._build_input_template(step_dict, step_type)

        # Get error handling (with defaults)
        retry_config = step_dict.get("retry", {})
        error_handling = self._get_error_handling(step_type, retry_config)
        max_retries = retry_config.get(
            "attempts", 3 if error_handling == ErrorHandling.RETRY else 0
        )

        # Get expected output schema
        expected_output_schema = step_dict.get("expect", {})

        # Build reasoning from description/instruction
        reasoning = step_dict.get("description") or step_dict.get("instruction", "")

        return PlanStep(
            step_id=step_id,
            step_type=step_type,
            action=action,
            tool_name=tool_name,
            input_template=input_template,
            expected_output_schema=expected_output_schema,
            error_handling=error_handling,
            max_retries=max_retries,
            reasoning=reasoning,
        )

    def _get_tool_name(self, step_dict: dict[str, Any], step_type: str) -> str:
        """Get tool name for a step."""
        if step_type == "tool.call":
            return step_dict["tool"]
        elif step_type.startswith("ai."):
            # AI operations are registered as MCP tools with the same name
            return step_type
        elif step_type in {"artifact.store", "artifact.retrieve"}:
            return step_type
        elif step_type == "webhook.wait":
            return "webhook_wait"
        else:
            # For condition, human.approval, etc. - use type as tool name
            return step_type

    def _build_input_template(self, step_dict: dict[str, Any], step_type: str) -> dict[str, Any]:
        """Build input template for a step."""
        if step_type == "tool.call":
            # Tool call: use params directly
            return step_dict.get("params", {})

        elif step_type.startswith("ai."):
            # AI operation: build AI-specific input
            return {
                "instruction": step_dict.get("instruction", ""),
                "data": step_dict.get("params", {}).get("data", {}),
                "expected_schema": step_dict.get("schema"),
                "temperature_override": step_dict.get("temperature"),
                "max_tokens_override": step_dict.get("max_tokens"),
                # Pass through any AI-specific extras
                **{
                    k: v
                    for k, v in step_dict.items()
                    if k
                    in {
                        "tools_allowlist",
                        "branches_enum",
                        "word_cap",
                        "candidates",
                        "rubric",
                        "glossary",
                        "top_k",
                    }
                },
            }

        elif step_type in {"artifact.store", "artifact.retrieve"}:
            return step_dict.get("params", {})

        elif step_type == "condition":
            return {"condition": step_dict.get("if", "true")}

        elif step_type == "webhook.wait":
            return step_dict.get("params", {})

        elif step_type == "human.approval":
            return step_dict.get("params", {})

        else:
            # Fallback: return params or empty dict
            return step_dict.get("params", {})

    def _get_error_handling(self, step_type: str, retry_config: dict[str, Any]) -> ErrorHandling:
        """Determine error handling strategy for a step."""
        # If retry is explicitly configured, use retry
        if retry_config.get("attempts", 0) > 0:
            return ErrorHandling.RETRY

        # Default strategies by step type
        if step_type == "human.approval":
            return ErrorHandling.ESCALATE

        elif step_type.startswith("ai."):
            # AI operations: retry by default (LLM calls can be transient failures)
            return ErrorHandling.RETRY

        elif step_type == "condition":
            # Conditions: fail workflow if evaluation fails
            return ErrorHandling.FAIL

        elif step_type == "tool.call":
            # Tools: retry by default (network calls, etc.)
            return ErrorHandling.RETRY

        else:
            # Default: retry
            return ErrorHandling.RETRY
