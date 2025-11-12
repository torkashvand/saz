"""Rule-based Planner - Deterministic workflow execution.

Reads workflow steps directly from YAML spec and converts them to executable plan steps.
Pure deterministic parsing - no LLM calls.
Cost-efficient: $0 for all workflows vs $0.10+ for LLM planner.
"""

from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

import structlog

from .schemas import ErrorHandling, ExecutionPlan, PlanStep, StepAction

logger = structlog.get_logger(__name__)


# Extras we allow to pass through to AI ops, if present in a step
_AI_EXTRA_KEYS: tuple[str, ...] = (
    "tools_allowlist",
    "branches_enum",
    "word_cap",
    "candidates",
    "rubric",
    "glossary",
    "top_k",
)


class RulePlanner:
    """Deterministic rule-based planner - pure YAML parsing, no LLM."""

    def __init__(self) -> None:
        """Initialize rule planner."""
        self.logger = logger.bind(agent="rule_planner")

        # Map exact step types to parser methods (dynamic for ai.* handled separately)
        self._parsers: dict[str, Callable[[dict[str, Any]], PlanStep]] = {
            "tool.call": self._parse_tool_call,
            "condition": self._parse_condition,
            "human.approval": self._parse_human_approval,
            "webhook.wait": self._parse_webhook_wait,
            "artifact.store": self._parse_artifact_store,
            "artifact.retrieve": self._parse_artifact_retrieve,
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
        Generate deterministic execution plan from workflow spec.

        Args:
            workflow_spec: Workflow specification with steps
            tool_registry: Available tools (unused - kept for protocol compatibility)
            run_id: Run identifier
            completed_steps: Already completed step IDs
            current_data: Execution context (unused - kept for protocol compatibility)
            budget: Budget constraints (unused - kept for protocol compatibility)

        Returns:
            ExecutionPlan with steps parsed from YAML
        """
        steps_spec: list[dict[str, Any]] = list(workflow_spec.get("steps", []))
        self.logger.info(
            "planning_workflow_deterministic",
            workflow=workflow_spec.get("name"),
            run_id=run_id,
            steps_total=len(steps_spec),
        )

        # Filter out already-completed steps
        remaining_steps = [s for s in steps_spec if s.get("id") not in completed_steps]

        plan_steps: list[PlanStep] = []

        for step_def in remaining_steps:
            step_type: str = step_def.get("type", "tool.call")

            if step_type.startswith("ai."):
                plan_step = self._parse_ai_op(step_def)
            else:
                parser = self._parsers.get(step_type)
                if not parser:
                    raise RuntimeError(f"unknown step type: {step_type}")
                plan_step = parser(step_def)

            plan_steps.append(plan_step)
            self.logger.debug(
                "parsed_step",
                step_id=plan_step.step_id,
                action=str(plan_step.action),
                tool=plan_step.tool_name,
            )

        plan = ExecutionPlan(
            plan_id=str(uuid4()),
            steps=plan_steps,
            estimated_cost_usd=0.0,
            estimated_time_seconds=len(plan_steps) * 2,
            reasoning="Deterministic rule-based plan from YAML workflow spec",
        )

        self.logger.info(
            "plan_generated_deterministic",
            plan_id=plan.plan_id,
            steps_count=len(plan_steps),
        )
        return plan

    # ---------------------------
    # Parsers (behavior preserved)
    # ---------------------------

    def _parse_ai_op(self, step_def: dict[str, Any]) -> PlanStep:
        """Parse ai.* step from YAML (handled as a TOOL_CALL to ai_ops)."""
        # Late import to avoid heavy module import at planner import-time
        from saz.agents.ai_ops import AI_OPS  # noqa: WPS433 (intentional local import)

        op_type: str = cast(str, step_def.get("type"))  # e.g., "ai.extract", "ai.generate"
        params: dict[str, Any] = step_def.get("params", {})
        retry: dict[str, Any] = step_def.get("retry", {})

        op_spec = AI_OPS.get(op_type)

        ai_params: dict[str, Any] = {
            "instruction": step_def.get("instruction") or step_def.get("description", ""),
            "data": params.get("data", {}),
        }

        # Optional overrides
        if "expect" in step_def or "schema" in step_def:
            ai_params["expected_schema"] = step_def.get("expect") or step_def.get("schema")
        if "temperature" in step_def:
            ai_params["temperature_override"] = step_def["temperature"]
        if "max_tokens" in step_def:
            ai_params["max_tokens_override"] = step_def["max_tokens"]

        # Pass-through extras
        for key in _AI_EXTRA_KEYS:
            if key in step_def:
                ai_params[key] = step_def[key]

        expected_schema = step_def.get("expect")
        if expected_schema is None and op_spec:
            expected_schema = op_spec.default_expect_schema
        if expected_schema is None:
            expected_schema = {}

        return PlanStep(
            step_id=step_def["id"],
            action=StepAction.TOOL_CALL,  # preserve original: AI ops are run as TOOL_CALL
            tool_name=op_type,
            input_template=ai_params,
            expected_output_schema=expected_schema,
            error_handling=ErrorHandling(
                "continue" if step_def.get("continue_on_fail", False) else "fail"
            ),
            max_retries=retry.get("attempts", 1),  # preserve: AI ops get 1 retry by default
            reasoning=step_def.get("description", f"Execute {op_type}"),
        )

    def _parse_tool_call(self, step_def: dict[str, Any]) -> PlanStep:
        """Parse tool.call step from YAML."""
        tool_name: str = step_def.get("tool", "http_request")
        params: dict[str, Any] = step_def.get("params", {})
        retry: dict[str, Any] = step_def.get("retry", {})

        return PlanStep(
            step_id=step_def["id"],
            action=StepAction.TOOL_CALL,
            tool_name=tool_name,
            input_template=params,
            expected_output_schema=step_def.get("expect") or {},
            error_handling=ErrorHandling(
                "continue" if step_def.get("continue_on_fail", False) else "fail"
            ),
            max_retries=retry.get("attempts", 0),
            reasoning=step_def.get("description", f"Execute {tool_name}"),
        )

    def _parse_condition(self, step_def: dict[str, Any]) -> PlanStep:
        """Parse condition step (evaluated via expression engine)."""
        return PlanStep(
            step_id=step_def["id"],
            action=StepAction.CONDITION,
            tool_name=None,
            input_template={"condition": step_def.get("if", "true")},
            expected_output_schema={
                "type": "object",
                "properties": {"result": {"type": "boolean"}},
            },
            error_handling=ErrorHandling.FAIL,
            max_retries=0,
            reasoning=step_def.get("description", "Evaluate condition"),
        )

    def _parse_human_approval(self, step_def: dict[str, Any]) -> PlanStep:
        """Parse human.approval step."""
        return PlanStep(
            step_id=step_def["id"],
            action=StepAction.HUMAN_APPROVAL,
            tool_name=None,
            input_template=step_def.get("params", {}),
            expected_output_schema=step_def.get("expect") or {},
            error_handling=ErrorHandling.ESCALATE,
            max_retries=0,
            reasoning=step_def.get("description", "Human approval required"),
        )

    def _parse_webhook_wait(self, step_def: dict[str, Any]) -> PlanStep:
        """Parse webhook.wait step."""
        return PlanStep(
            step_id=step_def["id"],
            action=StepAction.WEBHOOK_WAIT,
            tool_name="webhook_wait",
            input_template=step_def.get("params", {}),
            expected_output_schema=step_def.get("expect") or {},
            error_handling=ErrorHandling.FAIL,
            max_retries=0,
            reasoning=step_def.get("description", "Wait for webhook callback"),
        )

    def _parse_artifact_store(self, step_def: dict[str, Any]) -> PlanStep:
        """Parse artifact.store step."""
        return PlanStep(
            step_id=step_def["id"],
            action=StepAction.TOOL_CALL,
            tool_name="artifact_store",
            input_template=step_def.get("params", {}),
            expected_output_schema=step_def.get("expect") or {},
            error_handling=ErrorHandling.FAIL,
            max_retries=3,
            reasoning=step_def.get("description", "Store artifact"),
        )

    def _parse_artifact_retrieve(self, step_def: dict[str, Any]) -> PlanStep:
        """Parse artifact.retrieve step."""
        return PlanStep(
            step_id=step_def["id"],
            action=StepAction.TOOL_CALL,
            tool_name="artifact_retrieve",
            input_template=step_def.get("params", {}),
            expected_output_schema=step_def.get("expect") or {},
            error_handling=ErrorHandling.FAIL,
            max_retries=3,
            reasoning=step_def.get("description", "Retrieve artifact"),
        )
