"""Agentic Workflow Execution Engine.

Executes workflow runs with:
- Planning (rule-based or LLM-based)
- Tool execution via registry
- Retry logic with exponential backoff
- Budget tracking
- Conditional branching
- Artifact persistence
- Real-time event broadcasting
"""

import asyncio
import logging
import traceback
from datetime import UTC, datetime
from typing import Any

from saz.agents.executor import ExecutorAgent
from saz.agents.rule_planner import RulePlanner
from saz.agents.schemas import ErrorHandling, ExecutionPlan, PlanStep, StepAction
from saz.api.websocket import broadcast_events
from saz.db.unit_of_work import UnitOfWork
from saz.domain.events import RunCompleted, RunFailed, StepCompleted, StepFailed, StepStarted
from saz.engine.templating import TemplateContext
from saz.policies.budget_tracker import BudgetTracker
from saz.tools.registry import ToolRegistry, create_default_registry

logger = logging.getLogger(__name__)


class WorkflowExecutor:
    """Production-ready agentic workflow executor."""

    def __init__(
        self,
        uow: UnitOfWork,
        tool_registry: ToolRegistry | None = None,
        planner: RulePlanner | None = None,
        budget_tracker: BudgetTracker | None = None,
    ):
        """
        Initialize workflow executor.

        Args:
            uow: Unit of work for database operations
            tool_registry: Tool registry (creates default if not provided)
            planner: Planner agent (creates RulePlanner if not provided)
            budget_tracker: Budget tracker (creates default if not provided)
        """
        self.uow = uow
        self.tool_registry = tool_registry or create_default_registry(enable_ai_ops=True)
        self.planner = planner or RulePlanner()
        self.budget_tracker = budget_tracker or BudgetTracker()
        self.executor_agent = ExecutorAgent(secret_resolver=self._resolve_secret)

    async def execute_run(self, run_id: str) -> None:
        """
        Execute a workflow run end-to-end.

        Args:
            run_id: Run identifier
        """
        try:
            # Get run details
            assert self.uow.run_reads is not None
            run = self.uow.run_reads.detail(run_id)
            if not run:
                logger.error(f"Run not found: {run_id}")
                return

            # Get flow definition
            assert self.uow.flows is not None
            flow = self.uow.flows.get(run.flow_id)
            if not flow:
                logger.error(f"Flow not found: {run.flow_id}")
                await self._fail_run(
                    run_id,
                    {"message": f"Flow not found: {run.flow_id}", "type": "FlowNotFoundError"},
                )
                return

            # Mark run as running
            assert self.uow.runs is not None
            self.uow.runs.mark_running(run_id)
            self.uow.commit()

            logger.info(f"Starting agentic execution for run {run_id} (flow: {flow.name})")

            # Initialize budget
            budget_config = flow.definition.get("budget", {})
            self.budget_tracker.max_tokens = budget_config.get("max_tokens", 100000)
            self.budget_tracker.max_cost_usd = budget_config.get("max_cost_usd", 10.0)
            self.budget_tracker.max_steps = budget_config.get("max_steps", 50)
            self.budget_tracker.max_time_seconds = budget_config.get("max_time_seconds", 3600)
            self.budget_tracker.initialize_run(run_id)

            # Initialize execution context
            context: dict[str, Any] = {
                "run_id": run_id,
                "flow_id": flow.id,
                "payload": run.payload or {},
                "form_data": run.payload or {},
                "step_results": {},
                "artifacts": {},
                "completed_steps": [],
            }

            # Get workflow specification
            workflow_spec = flow.definition.get("workflow", {})
            if not workflow_spec:
                logger.warning(f"No workflow defined for flow {flow.id}")
                await self._complete_run(run_id)
                return

            # Generate execution plan
            plan = await self._generate_plan(
                workflow_spec=workflow_spec, run_id=run_id, context=context
            )

            logger.info(
                f"Generated plan with {len(plan.steps)} steps for run {run_id} "
                f"(estimated: ${plan.estimated_cost_usd:.3f}, {plan.estimated_time_seconds}s)"
            )

            # Execute plan steps sequentially
            for step_number, plan_step in enumerate(plan.steps):
                # Check budget before each step
                within_budget, budget_error = self.budget_tracker.check_budget(run_id)
                if not within_budget:
                    logger.error(f"Budget exceeded for run {run_id}: {budget_error}")
                    await self._fail_run(
                        run_id,
                        {
                            "message": f"Budget exceeded: {budget_error}",
                            "type": "BudgetExceededError",
                            "step": plan_step.step_id,
                            "step_number": step_number,
                        },
                    )
                    return

                # Execute step
                try:
                    step_result = await self._execute_plan_step(
                        run_id=run_id, step_number=step_number, plan_step=plan_step, context=context
                    )

                    # Update context with step result
                    context["step_results"][plan_step.step_id] = step_result
                    context["completed_steps"].append(plan_step.step_id)

                    # Record step execution in budget
                    self.budget_tracker.record_step(run_id)

                except Exception as step_error:
                    # Handle step failure based on error_handling policy
                    error_dict = {
                        "message": str(step_error),
                        "type": type(step_error).__name__,
                        "step": plan_step.step_id,
                        "step_number": step_number,
                        "traceback": "".join(
                            traceback.format_exception(
                                type(step_error), step_error, step_error.__traceback__
                            )[-5:]
                        ),
                    }

                    if plan_step.error_handling == ErrorHandling.FAIL:
                        logger.error(f"Step {plan_step.step_id} failed, failing run: {step_error}")
                        await self._fail_run(run_id, error_dict)
                        return

                    elif plan_step.error_handling == ErrorHandling.ESCALATE:
                        logger.error(f"Step {plan_step.step_id} requires escalation: {step_error}")
                        self.uow.runs.mark_suspended(run_id, error_dict)
                        self.uow.commit()
                        return

                    elif plan_step.error_handling == ErrorHandling.CONTINUE:
                        logger.warning(f"Step {plan_step.step_id} failed, continuing: {step_error}")
                        # Store error in step result
                        context["step_results"][plan_step.step_id] = {"error": error_dict}
                        context["completed_steps"].append(plan_step.step_id)
                        continue

                    else:
                        # RETRY is handled within _execute_plan_step
                        # If we reach here, retries exhausted
                        logger.error(f"Step {plan_step.step_id} retries exhausted: {step_error}")
                        await self._fail_run(run_id, error_dict)
                        return

            # All steps completed successfully
            await self._complete_run(run_id)

        except Exception as e:
            logger.exception(f"Fatal error executing run {run_id}: {e}")
            tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
            tb_snippet = "".join(tb_lines[-5:])
            await self._fail_run(
                run_id,
                {
                    "message": f"Fatal error: {str(e)}",
                    "type": type(e).__name__,
                    "traceback": tb_snippet,
                },
            )

    async def _generate_plan(
        self, workflow_spec: dict, run_id: str, context: dict
    ) -> ExecutionPlan:
        """
        Generate execution plan from workflow specification.

        Args:
            workflow_spec: Workflow YAML specification
            run_id: Run identifier
            context: Execution context

        Returns:
            ExecutionPlan with steps
        """
        # Get tool registry specs
        tool_specs = self.tool_registry.get_tool_specs()

        # Get remaining budget
        budget_remaining = self.budget_tracker.get_remaining(run_id)

        budget_dict = {
            "remaining_tokens": budget_remaining["tokens"]["remaining"],
            "max_tokens": self.budget_tracker.max_tokens,
            "remaining_cost": budget_remaining["cost"]["remaining"],
            "max_cost_usd": self.budget_tracker.max_cost_usd,
            "remaining_steps": budget_remaining["steps"]["remaining"],
            "max_steps": self.budget_tracker.max_steps,
        }

        # Generate plan using planner
        plan = await self.planner.plan(
            workflow_spec=workflow_spec,
            tool_registry=tool_specs,
            run_id=run_id,
            completed_steps=context.get("completed_steps", []),
            current_data=context.get("form_data", {}),
            budget=budget_dict,
        )

        return plan

    async def _execute_plan_step(
        self, run_id: str, step_number: int, plan_step: PlanStep, context: dict
    ) -> Any:
        """
        Execute a single plan step with retry logic.

        Args:
            run_id: Run identifier
            step_number: Step index
            plan_step: Plan step specification
            context: Execution context

        Returns:
            Step result

        Raises:
            Exception: If step fails after all retries
        """
        step_id = plan_step.step_id
        logger.info(f"Executing step {step_number}: {step_id} (action: {plan_step.action.value})")

        # Create step record
        assert self.uow.steps is not None
        step = self.uow.steps.append(
            run_id=run_id, number=step_number, name=step_id, status="running"
        )
        step.start_ts = datetime.now(UTC)
        self.uow.add_event(StepStarted(run_id, step_id, step_id, step_number))
        self.uow.commit()

        # Broadcast step started event
        events = self.uow.collect_events()
        await broadcast_events(events)

        # Execute with retries
        max_attempts = plan_step.max_retries + 1
        last_error = None

        for attempt in range(max_attempts):
            try:
                if attempt > 0:
                    # Exponential backoff
                    backoff = min(2**attempt, 30)  # Cap at 30 seconds
                    logger.info(
                        f"Retrying step {step_id}, attempt {attempt + 1}/{max_attempts} "
                        f"after {backoff}s"
                    )
                    await asyncio.sleep(backoff)

                # Execute step based on action type
                result = await self._execute_step_action(
                    plan_step=plan_step, context=context, run_id=run_id
                )

                # Success - mark step as completed
                step.status = "completed"
                step.end_ts = datetime.now(UTC)
                if step.start_ts and step.end_ts:
                    # Ensure both are timezone-aware
                    start = (
                        step.start_ts if step.start_ts.tzinfo else step.start_ts.replace(tzinfo=UTC)
                    )
                    end = step.end_ts if step.end_ts.tzinfo else step.end_ts.replace(tzinfo=UTC)
                    step.duration_ms = int((end - start).total_seconds() * 1000)

                # Store result
                step.output = result

                self.uow.add_event(
                    StepCompleted(
                        run_id=run_id,
                        step_id=step_id,
                        duration_ms=step.duration_ms or 0,
                        step_name=step_id,
                        step_number=step_number,
                        output=result,
                    )
                )
                self.uow.commit()

                # Broadcast step completed event
                events = self.uow.collect_events()
                await broadcast_events(events)

                logger.info(f"Step {step_id} completed successfully")
                return result

            except Exception as e:
                last_error = e
                logger.warning(f"Step {step_id} attempt {attempt + 1}/{max_attempts} failed: {e}")

                # If this is the last attempt, fail the step
                if attempt == max_attempts - 1:
                    step.status = "failed"
                    step.end_ts = datetime.now(UTC)
                    if step.start_ts and step.end_ts:
                        # Ensure both are timezone-aware
                        start = (
                            step.start_ts
                            if step.start_ts.tzinfo
                            else step.start_ts.replace(tzinfo=UTC)
                        )
                        end = step.end_ts if step.end_ts.tzinfo else step.end_ts.replace(tzinfo=UTC)
                        step.duration_ms = int((end - start).total_seconds() * 1000)

                    # Capture traceback
                    tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
                    tb_snippet = "".join(tb_lines[-5:])

                    error_dict = {
                        "message": str(e),
                        "type": type(e).__name__,
                        "traceback": tb_snippet,
                        "attempts": max_attempts,
                    }
                    step.error = error_dict

                    self.uow.add_event(
                        StepFailed(
                            run_id=run_id,
                            step_id=step_id,
                            error=error_dict,
                            step_name=step_id,
                            step_number=step_number,
                        )
                    )
                    self.uow.commit()

                    # Broadcast step failed event
                    events = self.uow.collect_events()
                    await broadcast_events(events)

                    logger.error(f"Step {step_id} failed after {max_attempts} attempts")
                    raise last_error from last_error

        # Should never reach here
        raise last_error or Exception(f"Step {step_id} failed without error")

    async def _execute_step_action(self, plan_step: PlanStep, context: dict, run_id: str) -> Any:
        """
        Execute step action (TOOL_CALL, CONDITION, HUMAN_APPROVAL, etc.).

        Args:
            plan_step: Plan step specification
            context: Execution context
            run_id: Run identifier

        Returns:
            Step result
        """
        if plan_step.action == StepAction.TOOL_CALL:
            return await self._execute_tool_call(plan_step, context, run_id)

        elif plan_step.action == StepAction.CONDITION:
            return await self._execute_condition(plan_step, context)

        elif plan_step.action == StepAction.HUMAN_APPROVAL:
            return await self._execute_human_approval(plan_step, context, run_id)

        elif plan_step.action == StepAction.WEBHOOK_WAIT:
            return await self._execute_webhook_wait(plan_step, context, run_id)

        elif plan_step.action == StepAction.AI_ASSESS:
            # AI_ASSESS is already handled as a tool call by RulePlanner
            return await self._execute_tool_call(plan_step, context, run_id)

        else:
            raise ValueError(f"Unknown step action: {plan_step.action}")

    async def _execute_tool_call(self, plan_step: PlanStep, context: dict, run_id: str) -> Any:
        """
        Execute a tool call with variable substitution.

        Args:
            plan_step: Plan step with tool_name and input_template
            context: Execution context
            run_id: Run identifier

        Returns:
            Tool execution result
        """
        # Ground step: substitute variables in input template
        tool_specs_dict = self.tool_registry.get_tool_specs_dict()

        tool_call = self.executor_agent.ground(
            step=plan_step,
            tool_registry=tool_specs_dict,
            current_data={**context["form_data"], **context["step_results"]},
            run_id=run_id,
        )

        logger.info(
            f"Executing tool {tool_call.tool} with idempotency key {tool_call.idempotency_key}"
        )

        # Execute tool
        result = await self.tool_registry.execute_tool(
            tool_name=tool_call.tool,
            arguments=tool_call.arguments,
            idempotency_key=tool_call.idempotency_key,
            run_id=run_id,
            step_id=plan_step.step_id,
        )

        # Track usage if present
        if isinstance(result, dict):
            usage = result.get("usage", {})
            if "tokens" in usage:
                self.budget_tracker.record_tokens(run_id, usage["tokens"])
            if "cost_usd" in usage:
                self.budget_tracker.record_cost(run_id, usage["cost_usd"])

        return result

    async def _execute_condition(self, plan_step: PlanStep, context: dict) -> Any:
        """
        Evaluate a conditional expression.

        Args:
            plan_step: Plan step with condition expression
            context: Execution context

        Returns:
            Boolean result
        """
        from saz.engine.expressions import evaluate_expression

        condition_expr = plan_step.input_template.get("condition", "true")

        # Resolve variables in condition
        template_context = TemplateContext(
            form_data=context["form_data"],
            step_results=context["step_results"],
            secret_resolver=self._resolve_secret,
        )
        resolved_condition = template_context.resolve(condition_expr)

        # Evaluate expression
        result = evaluate_expression(
            resolved_condition,
            context={"form": context["form_data"], "steps": context["step_results"]},
        )

        logger.info(f"Condition '{condition_expr}' evaluated to {result}")

        return {"result": result, "condition": resolved_condition}

    async def _execute_human_approval(self, plan_step: PlanStep, context: dict, run_id: str) -> Any:
        """
        Suspend run for human approval.

        Args:
            plan_step: Plan step
            context: Execution context
            run_id: Run identifier

        Returns:
            Approval request details
        """
        logger.info(f"Step {plan_step.step_id} requires human approval")

        # Suspend run
        assert self.uow.runs is not None
        self.uow.runs.mark_suspended(
            run_id,
            {
                "message": f"Human approval required for step {plan_step.step_id}",
                "type": "HumanApprovalRequired",
                "step_id": plan_step.step_id,
                "reasoning": plan_step.reasoning,
            },
        )
        self.uow.commit()

        return {
            "status": "awaiting_approval",
            "step_id": plan_step.step_id,
            "reasoning": plan_step.reasoning,
        }

    async def _execute_webhook_wait(self, plan_step: PlanStep, context: dict, run_id: str) -> Any:
        """
        Wait for webhook callback (delegates to webhook tool).

        Args:
            plan_step: Plan step
            context: Execution context
            run_id: Run identifier

        Returns:
            Webhook data
        """
        # Execute via tool registry (webhook_wait tool)
        return await self._execute_tool_call(plan_step, context, run_id)

    async def _complete_run(self, run_id: str) -> None:
        """
        Mark run as completed and broadcast event.

        Args:
            run_id: Run identifier
        """
        assert self.uow.runs is not None
        self.uow.runs.mark_completed(run_id)
        self.uow.add_event(RunCompleted(run_id))
        self.uow.commit()

        events = self.uow.collect_events()
        await broadcast_events(events)

        # Log budget stats
        budget_stats = self.budget_tracker.get_remaining(run_id)
        logger.info(
            f"Run {run_id} completed successfully. "
            f"Budget used: {budget_stats['tokens']['used']} tokens, "
            f"${budget_stats['cost']['used']:.3f}, "
            f"{budget_stats['steps']['used']} steps, "
            f"{budget_stats['time']['used_seconds']:.1f}s"
        )

    async def _fail_run(self, run_id: str, error: dict) -> None:
        """
        Mark run as failed and broadcast event.

        Args:
            run_id: Run identifier
            error: Error details
        """
        assert self.uow.runs is not None
        self.uow.runs.mark_failed(run_id, error)
        self.uow.add_event(RunFailed(run_id, error))
        self.uow.commit()

        events = self.uow.collect_events()
        await broadcast_events(events)

        logger.error(f"Run {run_id} failed: {error.get('message', 'Unknown error')}")

    def _resolve_secret(self, secret_name: str) -> str | None:
        """
        Resolve secret from credentials store.

        Args:
            secret_name: Credential name

        Returns:
            Secret value or None
        """
        try:
            import os

            import yaml
            from cryptography.fernet import Fernet

            assert self.uow.credentials is not None
            credential = self.uow.credentials.get(secret_name)
            if not credential:
                return None

            # Decrypt credential data
            key = os.getenv("CREDENTIALS_ENCRYPTION_KEY")
            if not key:
                # Generate key if not set (dev only)
                key = Fernet.generate_key().decode()
            cipher = Fernet(key.encode() if isinstance(key, str) else key)

            decrypted = cipher.decrypt(credential.data_encrypted)
            data = yaml.safe_load(decrypted.decode())

            if isinstance(data, dict):
                # Extract first value from data dict (API key, token, etc.)
                return next(iter(data.values()), None)
            return str(data)

        except Exception as e:
            logger.warning(f"Failed to resolve secret '{secret_name}': {e}")
            return None
