"""Rule-based Planner - Deterministic workflow execution (no LLM by default).

Reads workflow steps directly from YAML spec.
Only invokes LLM for optional "ai.assess" step type.
Cost-efficient: ~$0 for typical workflows vs $0.10+ for LLM planner.
"""
import json
import structlog
from typing import Dict, Any, List
from uuid import uuid4
from litellm import completion
from .schemas import ExecutionPlan, PlanStep, StepAction, ErrorHandling

logger = structlog.get_logger(__name__)


class RulePlanner:
    """Deterministic rule-based planner (LLM-free by default)."""

    def __init__(self, model: str = "gpt-4o-mini"):
        """
        Initialize rule planner.

        Args:
            model: LLM model for optional ai.assess steps (cheaper model default)
        """
        self.model = model
        self.logger = logger.bind(agent="rule_planner")

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
        Generate execution plan from workflow spec (deterministic).

        Args:
            workflow_spec: Parsed YAML workflow with steps
            tool_registry: Available tools
            run_id: Current run ID
            completed_steps: Already executed step IDs
            current_data: Current execution context
            budget: Remaining budget

        Returns:
            ExecutionPlan with steps parsed from YAML
        """
        self.logger.info(
            "planning_workflow_deterministic",
            workflow=workflow_spec.get('name'),
            run_id=run_id,
            steps_total=len(workflow_spec.get('steps', []))
        )

        steps_spec = workflow_spec.get('steps', [])
        plan_steps = []
        llm_cost = 0.0

        # Filter out already completed steps
        remaining_steps = [s for s in steps_spec if s.get('id') not in completed_steps]

        for step_def in remaining_steps:
            step_id = step_def.get('id')
            step_type = step_def.get('type', 'tool.call')

            # Parse step based on type
            if step_type.startswith('ai.'):
                # AI operation - treat as tool call with AI ops runner
                plan_step = self._parse_ai_op(step_def, tool_registry)
            elif step_type == 'tool.call':
                plan_step = self._parse_tool_call(step_def, tool_registry)
            elif step_type == 'condition':
                plan_step = self._parse_condition(step_def)
            elif step_type == 'human.approval':
                plan_step = self._parse_human_approval(step_def)
            elif step_type == 'webhook.wait':
                plan_step = self._parse_webhook_wait(step_def)
            elif step_type == 'artifact.store':
                plan_step = self._parse_artifact_store(step_def)
            elif step_type == 'artifact.retrieve':
                plan_step = self._parse_artifact_retrieve(step_def)
            else:
                # Default: treat as tool call
                plan_step = self._parse_tool_call(step_def, tool_registry)

            plan_steps.append(plan_step)

        plan = ExecutionPlan(
            plan_id=str(uuid4()),
            steps=plan_steps,
            estimated_cost_usd=llm_cost,
            estimated_time_seconds=len(plan_steps) * 2,  # 2s per step estimate
            reasoning="Deterministic rule-based plan from YAML workflow spec"
        )

        self.logger.info(
            "plan_generated_deterministic",
            plan_id=plan.plan_id,
            steps_count=len(plan_steps),
            llm_steps=sum(1 for s in plan_steps if s.action == StepAction.AI_ASSESS),
            llm_cost=llm_cost
        )

        return plan

    def _parse_ai_op(self, step_def: Dict, tool_registry: List[Dict]) -> PlanStep:
        """Parse ai.* step from YAML."""
        op_type = step_def.get('type')
        params = step_def.get('params', {})
        retry = step_def.get('retry', {})

        # Get default schema from AI_OPS registry
        from saz.agents.ai_ops import AI_OPS
        op_spec = AI_OPS.get(op_type)

        # Build params with instruction
        ai_params = {
            'instruction': step_def.get('instruction') or step_def.get('description', ''),
            'data': params.get('data', {}),
        }

        # Add overrides if present
        if 'expect' in step_def or 'schema' in step_def:
            ai_params['expected_schema'] = step_def.get('expect') or step_def.get('schema')
        if 'temperature' in step_def:
            ai_params['temperature_override'] = step_def['temperature']
        if 'max_tokens' in step_def:
            ai_params['max_tokens_override'] = step_def['max_tokens']

        # Add operation-specific extras
        for extra_key in ['tools_allowlist', 'branches_enum', 'word_cap', 'candidates', 'rubric', 'glossary', 'top_k']:
            if extra_key in step_def:
                ai_params[extra_key] = step_def[extra_key]

        return PlanStep(
            step_id=step_def['id'],
            action=StepAction.TOOL_CALL,
            tool_name=op_type,
            input_template=ai_params,
            expected_output_schema=step_def.get('expect', op_spec.default_expect_schema if op_spec else {}),
            error_handling=ErrorHandling(step_def.get('continue_on_fail', False) and 'continue' or 'fail'),
            max_retries=retry.get('attempts', 1),  # AI ops get 1 retry by default
            reasoning=step_def.get('description', f"Execute {op_type}")
        )

    def _parse_tool_call(self, step_def: Dict, tool_registry: List[Dict]) -> PlanStep:
        """Parse tool.call step from YAML."""
        tool_name = step_def.get('tool', 'http_request')
        params = step_def.get('params', {})
        retry = step_def.get('retry', {})

        return PlanStep(
            step_id=step_def['id'],
            action=StepAction.TOOL_CALL,
            tool_name=tool_name,
            input_template=params,
            expected_output_schema=step_def.get('expect', {}),
            error_handling=ErrorHandling(step_def.get('continue_on_fail', False) and 'continue' or 'fail'),
            max_retries=retry.get('attempts', 0),
            reasoning=step_def.get('description', f"Execute {tool_name}")
        )

    def _parse_condition(self, step_def: Dict) -> PlanStep:
        """Parse condition step (evaluated via expression engine)."""
        return PlanStep(
            step_id=step_def['id'],
            action=StepAction.CONDITION,
            tool_name=None,
            input_template={"condition": step_def.get('if', 'true')},
            expected_output_schema={"type": "object", "properties": {"result": {"type": "boolean"}}},
            error_handling=ErrorHandling.FAIL,
            max_retries=0,
            reasoning=step_def.get('description', "Evaluate condition")
        )

    def _parse_human_approval(self, step_def: Dict) -> PlanStep:
        """Parse human.approval step."""
        return PlanStep(
            step_id=step_def['id'],
            action=StepAction.HUMAN_APPROVAL,
            tool_name=None,
            input_template=step_def.get('params', {}),
            expected_output_schema=step_def.get('expect', {}),
            error_handling=ErrorHandling.ESCALATE,
            max_retries=0,
            reasoning=step_def.get('description', "Human approval required")
        )

    def _parse_webhook_wait(self, step_def: Dict) -> PlanStep:
        """Parse webhook.wait step."""
        return PlanStep(
            step_id=step_def['id'],
            action=StepAction.WEBHOOK_WAIT,
            tool_name="webhook_wait",
            input_template=step_def.get('params', {}),
            expected_output_schema=step_def.get('expect', {}),
            error_handling=ErrorHandling.FAIL,
            max_retries=0,
            reasoning=step_def.get('description', "Wait for webhook callback")
        )

    def _parse_artifact_store(self, step_def: Dict) -> PlanStep:
        """Parse artifact.store step."""
        return PlanStep(
            step_id=step_def['id'],
            action=StepAction.TOOL_CALL,
            tool_name="artifact_store",
            input_template=step_def.get('params', {}),
            expected_output_schema=step_def.get('expect', {}),
            error_handling=ErrorHandling.FAIL,
            max_retries=3,
            reasoning=step_def.get('description', "Store artifact")
        )

    def _parse_artifact_retrieve(self, step_def: Dict) -> PlanStep:
        """Parse artifact.retrieve step."""
        return PlanStep(
            step_id=step_def['id'],
            action=StepAction.TOOL_CALL,
            tool_name="artifact_retrieve",
            input_template=step_def.get('params', {}),
            expected_output_schema=step_def.get('expect', {}),
            error_handling=ErrorHandling.FAIL,
            max_retries=3,
            reasoning=step_def.get('description', "Retrieve artifact")
        )

    async def _parse_ai_assess(
        self,
        step_def: Dict,
        current_data: Dict,
        budget: Dict
    ) -> tuple[PlanStep, float]:
        """
        Parse ai.assess step (uses LLM with strict schema).

        Returns:
            Tuple of (PlanStep, cost_usd)
        """
        self.logger.info("ai_assess_invoked", step_id=step_def['id'])

        prompt = f"""Assess the following data and provide a structured decision.

Step description: {step_def.get('description', 'Assess data')}
Current data: {json.dumps(current_data, indent=2, default=str)}

Expected output schema:
{json.dumps(step_def.get('expect', {}), indent=2)}

Respond with ONLY valid JSON matching the expected schema. Be concise."""

        try:
            response = completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a data assessment agent. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )

            assessment_result = json.loads(response.choices[0].message.content)
            tokens_used = response.usage.total_tokens

            # Estimate cost (rough: $0.15/$0.60 per 1M tokens for gpt-4o-mini)
            cost = (tokens_used / 1_000_000) * 0.20

            self.logger.info(
                "ai_assess_complete",
                step_id=step_def['id'],
                tokens=tokens_used,
                cost_usd=cost
            )

            return PlanStep(
                step_id=step_def['id'],
                action=StepAction.AI_ASSESS,
                tool_name=None,
                input_template={"assessment_result": assessment_result},
                expected_output_schema=step_def.get('expect', {}),
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
                reasoning=f"AI assessment: {step_def.get('description', 'Assess')}"
            ), cost

        except Exception as e:
            self.logger.error("ai_assess_failed", step_id=step_def['id'], error=str(e))
            # Return fallback step with error
            return PlanStep(
                step_id=step_def['id'],
                action=StepAction.TOOL_CALL,
                tool_name="artifact_store",
                input_template={"name": f"{step_def['id']}_error", "content": str(e)},
                expected_output_schema={},
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
                reasoning=f"AI assessment failed: {str(e)}"
            ), 0.0
