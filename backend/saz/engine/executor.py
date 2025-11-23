"""Workflow Execution Engine with Dual Planning Modes.

Supports two planning modes (chosen per-flow via workflow.planner_mode):

1. Deterministic mode (planner_mode: deterministic):
   - Converts workflow.steps 1:1 to execution plan
   - No LLM for graph planning ($0 planning cost)
   - LLMs used only inside ai.* steps

2. Agentic mode (planner_mode: agentic):
   - LLM planner generates execution plan dynamically
   - Reads DSL + tools + budget → produces ExecutionPlan
   - Planning cost ~$0.01-0.10 per run

Common features:
- Tool execution via MCP registry
- Retry logic with configurable backoff
- Budget tracking and policy enforcement
- Conditional branching and human approval gates
- Artifact persistence and real-time event broadcasting
"""

import asyncio
import logging
import traceback
from datetime import UTC, datetime
from typing import Any

from saz.agents.critic import CriticAgent
from saz.agents.executor import ExecutorAgent
from saz.agents.planner_protocol import Planner
from saz.agents.schemas import (
    Critique,
    ErrorHandling,
    ExecutionPlan,
    PlanStep,
    Verdict,
)
from saz.audit.event_emitter import EventEmitter
from saz.db.models import Step
from saz.db.unit_of_work import UnitOfWork
from saz.engine.templating import TemplateContext
from saz.policies.policy_engine import PolicyEngine
from saz.settings import settings
from saz.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


# Exception classes for agentic loop
class PolicyViolation(Exception):
    """Raised when policy check fails"""

    pass


class CritiqueFailure(Exception):
    """Raised when critic returns FAIL verdict"""

    def __init__(self, message: str, critique: Critique):
        super().__init__(message)
        self.critique = critique


class EscalationRequired(Exception):
    """Raised when critic returns ESCALATE verdict"""

    def __init__(self, message: str, critique: Critique):
        super().__init__(message)
        self.critique = critique


class ReplanRequired(Exception):
    """Raised when critic returns REPLAN verdict"""

    def __init__(self, message: str, critique: Critique):
        super().__init__(message)
        self.critique = critique


class WorkflowExecutor:
    """Production-ready agentic workflow executor."""

    def __init__(
        self,
        uow: UnitOfWork,
        tool_registry: ToolRegistry,
        planner: Planner,
        executor_agent: ExecutorAgent,
        critic: CriticAgent,
        policy_engine: PolicyEngine,
    ):
        """
        Initialize workflow executor.

        Args:
            uow: Unit of work for database operations
            tool_registry: Tool registry
            planner: Planner (any implementation of Planner protocol)
            executor_agent: Executor agent for grounding
            critic: Critic agent for validation
            policy_engine: Policy engine for enforcement
        """
        self.uow = uow
        self.tool_registry = tool_registry
        self.planner = planner
        self.executor_agent = executor_agent
        self.critic = critic
        self.policy_engine = policy_engine

        # Set secret resolver for executor agent
        self.executor_agent.secret_resolver = self._resolve_secret

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
                # Create minimal emitter for error case
                emitter = EventEmitter(
                    uow=self.uow,
                    run_id=run_id,
                    planner_mode="deterministic",
                    pii_policy="redact",
                )
                await self._fail_run(
                    run_id,
                    {"message": f"Flow not found: {run.flow_id}", "type": "FlowNotFoundError"},
                    emitter,
                )
                return

            # Mark run as running
            assert self.uow.runs is not None
            self.uow.runs.mark_running(run_id)

            # Get planner mode from workflow spec
            workflow_spec = flow.definition.get("workflow", {})
            planner_mode = workflow_spec.get("planner_mode", "deterministic")

            # Get PII policy from DSL
            policies_dict = flow.definition.get("policies", {})
            pii_policy = policies_dict.get("pii", {}).get("mode", "redact")

            # Initialize event emitter
            emitter = EventEmitter(
                uow=self.uow,
                run_id=run_id,
                planner_mode=planner_mode,
                pii_policy=pii_policy,
            )

            # Emit run started event
            emitter.run_started(flow_id=flow.id, flow_name=flow.name)
            await emitter.commit_and_broadcast()

            logger.info(f"Starting agentic execution for run {run_id} (flow: {flow.name})")

            # Initialize policy engine from DSL
            self.policy_engine.initialize_from_dsl(run_id, policies_dict)

            # Initialize execution context
            context: dict[str, Any] = {
                "run_id": run_id,
                "flow_id": flow.id,
                "payload": run.payload or {},
                "form_data": run.payload or {},
                "step_results": {},
                "artifacts": {},
                "completed_steps": [],
                "emitter": emitter,  # Pass emitter in context for nested calls
            }

            # Check if workflow exists
            if not workflow_spec:
                logger.warning(f"No workflow defined for flow {flow.id}")
                await self._complete_run(run_id, emitter)
                return

            # Generate execution plan
            plan = await self._generate_plan(
                workflow_spec=workflow_spec, run_id=run_id, context=context
            )

            logger.info(
                f"Generated plan with {len(plan.steps)} steps for run {run_id} "
                f"(estimated: ${plan.estimated_cost_usd:.3f}, {plan.estimated_time_seconds}s)"
            )

            # Emit plan generated event
            steps_summary = [
                {
                    "id": step.step_id,
                    "intent": step.reasoning,
                    "deps": getattr(step, "dependencies", []),
                }
                for step in plan.steps
            ]
            emitter.plan_generated(
                total_steps=len(plan.steps),
                steps=steps_summary,
                estimated_cost=plan.estimated_cost_usd,
            )
            await emitter.commit_and_broadcast()

            # Execute plan steps sequentially
            for step_number, plan_step in enumerate(plan.steps):
                # Check budget before each step
                within_budget, budget_error = self.policy_engine.budget_tracker.check_budget(run_id)
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
                        emitter,
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

                    # Record step execution in policy engine
                    self.policy_engine.record_step(run_id)

                    # Emit usage event (if tokens/cost available)
                    step_entity = self._get_current_step(run_id, plan_step.step_id)
                    if step_entity.tokens and step_entity.tokens > 0:
                        emitter.usage_recorded(
                            step_id=step_entity.id,
                            tokens=step_entity.tokens or 0,
                            cost_usd=step_entity.cost_usd or 0.0,
                            duration_ms=step_entity.duration_ms or 0,
                        )

                    # Emit progress event
                    completed = len(context["completed_steps"])
                    total = len(plan.steps)
                    percent = (completed / total) * 100 if total > 0 else 0
                    emitter.progress_updated(
                        completed=completed,
                        total=total,
                        percent=percent,
                    )
                    await emitter.commit_and_broadcast()

                except PolicyViolation as step_error:
                    # Policy violation - always fail immediately
                    error_dict = {
                        "message": str(step_error),
                        "type": "PolicyViolation",
                        "step": plan_step.step_id,
                        "step_number": step_number,
                    }
                    logger.error(f"Step {plan_step.step_id} blocked by policy: {step_error}")
                    await self._fail_run(run_id, error_dict, emitter)
                    return

                except CritiqueFailure as step_error:
                    # Critique failed - store critique and fail
                    error_dict = {
                        "message": str(step_error),
                        "type": "CritiqueFailure",
                        "step": plan_step.step_id,
                        "step_number": step_number,
                        "critique": step_error.critique.model_dump(),
                    }
                    logger.error(f"Step {plan_step.step_id} failed critique: {step_error}")
                    await self._fail_run(run_id, error_dict, emitter)
                    return

                except EscalationRequired as step_error:
                    # Escalation required - suspend run
                    error_dict = {
                        "message": str(step_error),
                        "type": "EscalationRequired",
                        "step": plan_step.step_id,
                        "step_number": step_number,
                        "critique": step_error.critique.model_dump(),
                    }
                    logger.warning(f"Step {plan_step.step_id} requires escalation: {step_error}")
                    self.uow.runs.mark_suspended(run_id, error_dict)
                    self.uow.commit()
                    return

                except ReplanRequired as step_error:
                    # Replanning required - treat as failure for now
                    error_dict = {
                        "message": str(step_error),
                        "type": "ReplanRequired",
                        "step": plan_step.step_id,
                        "step_number": step_number,
                        "critique": step_error.critique.model_dump(),
                    }
                    logger.warning(f"Step {plan_step.step_id} requires replanning: {step_error}")
                    await self._fail_run(run_id, error_dict, emitter)
                    return

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
                        await self._fail_run(run_id, error_dict, emitter)
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
                        await self._fail_run(run_id, error_dict, emitter)
                        return

            # All steps completed successfully
            await self._complete_run(run_id, emitter)

        except Exception as e:
            logger.exception(f"Fatal error executing run {run_id}: {e}")
            tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
            tb_snippet = "".join(tb_lines[-5:])

            # Create emitter for error case (if not already created)
            try:
                emitter = context.get("emitter")  # type: ignore
            except (NameError, UnboundLocalError):
                # If context wasn't created, create a minimal emitter
                emitter = EventEmitter(
                    uow=self.uow,
                    run_id=run_id,
                    planner_mode="deterministic",
                    pii_policy="redact",
                )

            await self._fail_run(
                run_id,
                {
                    "message": f"Fatal error: {str(e)}",
                    "type": type(e).__name__,
                    "traceback": tb_snippet,
                },
                emitter,
            )

    async def _generate_plan(
        self, workflow_spec: dict, run_id: str, context: dict
    ) -> ExecutionPlan:
        """
        Generate ExecutionPlan using self.planner (chosen at construction time).

        The planner type (DeterministicPlanner or AgenticPlanner) is selected when the executor
        is instantiated based on the flow's planner_mode.

        Args:
            workflow_spec: Workflow YAML specification (includes planner_mode)
            run_id: Run identifier
            context: Execution context

        Returns:
            ExecutionPlan from the injected planner
        """
        # Get tool registry specs
        tool_specs = self.tool_registry.get_tool_specs()

        # Get remaining budget from policy engine
        budget_remaining = self.policy_engine.get_budget_status(run_id)

        budget_dict = {
            "remaining_tokens": budget_remaining["tokens"]["remaining"],
            "max_tokens": self.policy_engine.budget_tracker.max_tokens,
            "remaining_cost": budget_remaining["cost"]["remaining"],
            "max_cost_usd": self.policy_engine.budget_tracker.max_cost_usd,
            "remaining_steps": budget_remaining["steps"]["remaining"],
            "max_steps": self.policy_engine.budget_tracker.max_steps,
        }

        # Generate plan using injected planner (type chosen at construction)
        planner_mode = workflow_spec["planner_mode"]
        logger.info(
            f"Planning workflow for run {run_id} (mode: {planner_mode}, "
            f"steps: {len(workflow_spec.get('steps', []))})"
        )

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
        logger.info(f"Executing step {step_number}: {step_id} (type: {plan_step.step_type})")

        # Get emitter from context
        emitter: EventEmitter = context["emitter"]

        # Create step record
        assert self.uow.steps is not None
        step = self.uow.steps.append(
            run_id=run_id,
            number=step_number,
            name=step_id,
            step_type=plan_step.step_type,
            status="running",
        )
        step.start_ts = datetime.now(UTC)
        self.uow.commit()

        # Store step record in context for use in tool calls
        context["current_step"] = step

        # Emit step started event (use step.id, not step_id which is the name)
        emitter.step_started(step_id=step.id, step_name=step_id, step_number=step_number)
        await emitter.commit_and_broadcast()

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
                self.uow.commit()

                # Emit step completed event
                emitter.step_completed(
                    step_id=step.id,
                    step_name=step_id,
                    duration_ms=step.duration_ms or 0,
                )
                await emitter.commit_and_broadcast()

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
                    self.uow.commit()

                    # Emit step failed event
                    emitter.step_failed(
                        step_id=step.id,
                        step_name=step_id,
                        error=str(error_dict["message"]),
                        error_type=str(error_dict["type"]),
                    )
                    await emitter.commit_and_broadcast()

                    logger.error(f"Step {step_id} failed after {max_attempts} attempts")
                    raise last_error from last_error

        # Should never reach here
        raise last_error or Exception(f"Step {step_id} failed without error")

    async def _execute_step_action(self, plan_step: PlanStep, context: dict, run_id: str) -> Any:
        """
        Execute step based on step_type.

        Args:
            plan_step: Plan step specification
            context: Execution context
            run_id: Run identifier

        Returns:
            Step result
        """
        t = plan_step.step_type

        # AI operations and tool.call → execute as tool call
        if t.startswith("ai.") or t == "tool.call" or t.startswith("artifact."):
            return await self._execute_tool_call(plan_step, context, run_id)

        # Condition evaluation
        elif t == "condition":
            return await self._execute_condition(plan_step, context)

        # Human approval gates
        elif t == "human.approval":
            return await self._execute_human_approval(plan_step, context, run_id)

        # Webhook wait
        elif t == "webhook.wait":
            return await self._execute_webhook_wait(plan_step, context, run_id)

        else:
            raise ValueError(
                f"Unknown step_type: {t!r}. "
                f"Expected: ai.*, tool.call, artifact.*, condition, human.approval, or webhook.wait"
            )

    async def _execute_tool_call(self, plan_step: PlanStep, context: dict, run_id: str) -> Any:
        """
        Execute tool call with full agentic cycle:
        1. Ground step (ExecutorAgent)
        2. Policy check (PolicyEngine)
        3. Execute tool (ToolRegistry)
        4. Redact output (PolicyEngine)
        5. Critique result (CriticAgent)
        6. Handle verdict

        Args:
            plan_step: Plan step with tool_name and input_template
            context: Execution context
            run_id: Run identifier

        Returns:
            Tool execution result

        Raises:
            PolicyViolation: If policy check fails
            CritiqueFailure: If critic returns FAIL verdict
            EscalationRequired: If critic returns ESCALATE verdict
            ReplanRequired: If critic returns REPLAN verdict
        """
        # Get emitter from context
        emitter: EventEmitter = context["emitter"]

        # 1. Ground step
        tool_specs_dict = self.tool_registry.get_tool_specs_dict()
        tool_call = self.executor_agent.ground(
            step=plan_step,
            tool_registry=tool_specs_dict,
            current_data=context,
            run_id=run_id,
        )

        logger.info(
            "grounding_step",
            extra={
                "run_id": run_id,
                "step_id": plan_step.step_id,
                "tool": tool_call.tool,
                "idempotency_key": tool_call.idempotency_key,
            },
        )

        # Store grounded input in step record
        step = self._get_current_step(run_id, plan_step.step_id)
        step.input = {"tool": tool_call.tool, "arguments": tool_call.arguments}
        self.uow.commit()

        # 2. Policy check (before tokenization, to detect raw PII)
        allowed, reason = self.policy_engine.check_tool_call(
            tool_name=tool_call.tool,
            arguments=tool_call.arguments,
            run_id=run_id,
        )

        if not allowed:
            # Record policy violation
            step.policy_flags = {"blocked": True, "reason": reason}
            self.uow.commit()
            logger.warning(
                "policy_violation",
                extra={
                    "run_id": run_id,
                    "step_id": plan_step.step_id,
                    "tool": tool_call.tool,
                    "reason": reason,
                },
            )
            raise PolicyViolation(f"Tool call blocked: {reason}")

        # 2a. Apply PII transformations based on tool type
        # - Model tools: tokenize inputs (LLMs never see raw PII)
        # - Outbound tools: selectively detokenize based on allow-list
        if self.policy_engine._is_model_tool(tool_call.tool):
            tool_call.arguments = self.policy_engine.tokenize_arguments(
                tool_name=tool_call.tool,
                arguments=tool_call.arguments,
                run_id=run_id,
            )
        elif self.policy_engine._is_outbound_tool(tool_call.tool):
            tool_call.arguments = self.policy_engine.detokenize_arguments(
                tool_name=tool_call.tool,
                arguments=tool_call.arguments,
                run_id=run_id,
            )

        # 3. Execute tool
        logger.info(
            f"Executing tool {tool_call.tool} with idempotency key {tool_call.idempotency_key}"
        )

        # Get step UUID from context
        current_step: Step = context["current_step"]

        # Emit tool started event
        emitter.tool_started(step_id=current_step.id, tool_name=tool_call.tool, attempt=1)
        await emitter.commit_and_broadcast()

        tool_start_time = datetime.now()
        try:
            result = await self.tool_registry.execute_tool(
                tool_name=tool_call.tool,
                arguments=tool_call.arguments,
                idempotency_key=tool_call.idempotency_key,
                run_id=run_id,
                step_id=plan_step.step_id,
            )

            # Tool succeeded
            tool_duration_ms = int((datetime.now() - tool_start_time).total_seconds() * 1000)
            emitter.tool_succeeded(
                step_id=current_step.id,
                tool_name=tool_call.tool,
                duration_ms=tool_duration_ms,
            )
            await emitter.commit_and_broadcast()

        except Exception as tool_error:
            # Tool failed
            tool_duration_ms = int((datetime.now() - tool_start_time).total_seconds() * 1000)
            emitter.tool_failed(
                step_id=current_step.id,
                tool_name=tool_call.tool,
                error=str(tool_error),
                error_type=type(tool_error).__name__,
            )
            await emitter.commit_and_broadcast()
            raise

        # 4. Extract and record AI usage
        tokens = 0
        cost_usd = 0.0
        if isinstance(result, dict):
            usage = result.get("usage", {})
            tokens = usage.get("tokens", 0)
            cost_usd = usage.get("cost_usd", 0.0)

            if tokens > 0:
                self.policy_engine.record_llm_usage(run_id, tokens, cost_usd)
                step.tokens = tokens
                step.cost_usd = cost_usd
                self.uow.commit()

        logger.info(
            "tool_executed",
            extra={
                "run_id": run_id,
                "step_id": plan_step.step_id,
                "tool": tool_call.tool,
                "tokens": tokens,
                "cost": cost_usd,
            },
        )

        # 5. Redact PII from output
        redacted_result = self.policy_engine.redact_output(
            data=result if isinstance(result, dict) else {"value": result},
            run_id=run_id,
        )

        # 6. Critique result
        critique = await self.critic.critique(
            step=plan_step,
            tool_call={"tool": tool_call.tool, "arguments": tool_call.arguments},
            result=redacted_result,
            run_id=run_id,
            completed_steps=context.get("completed_steps", []),
            current_state=context.get("step_results", {}),
        )

        # Store critique in step
        step.critique = critique.model_dump()
        self.uow.commit()

        logger.info(
            "critique_received",
            extra={
                "run_id": run_id,
                "step_id": plan_step.step_id,
                "verdict": critique.verdict.value,
                "confidence": critique.confidence,
                "issues_count": len(critique.issues),
            },
        )

        # 7. Handle verdict
        if critique.verdict == Verdict.PASS:
            logger.info(
                f"Step {plan_step.step_id} passed critique",
                extra={"confidence": critique.confidence},
            )
            return redacted_result

        elif critique.verdict == Verdict.FAIL:
            logger.error(
                f"Step {plan_step.step_id} failed critique",
                extra={"reasoning": critique.reasoning},
            )
            raise CritiqueFailure(f"Critique failed: {critique.reasoning}", critique=critique)

        elif critique.verdict == Verdict.ESCALATE:
            logger.warning(
                f"Step {plan_step.step_id} requires human escalation",
                extra={"reasoning": critique.reasoning},
            )
            raise EscalationRequired(
                f"Human approval required: {critique.reasoning}", critique=critique
            )

        elif critique.verdict == Verdict.REPLAN:
            logger.warning(
                f"Step {plan_step.step_id} requires replanning",
                extra={"reasoning": critique.reasoning},
            )
            # For now, treat as failure (full replanning not implemented in this phase)
            raise ReplanRequired(f"Replanning required: {critique.reasoning}", critique=critique)

        return redacted_result

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

    async def _complete_run(self, run_id: str, emitter: EventEmitter) -> None:
        """
        Mark run as completed and broadcast event.

        Args:
            run_id: Run identifier
            emitter: Event emitter for broadcasting events
        """
        assert self.uow.runs is not None
        self.uow.runs.mark_completed(run_id)
        self.uow.commit()

        # Get budget stats for logging
        budget_stats = self.policy_engine.get_budget_status(run_id)

        # Emit run completed event
        emitter.run_completed(
            tokens=budget_stats["tokens"]["used"],
            cost_usd=budget_stats["cost"]["used"],
            steps=budget_stats["steps"]["used"],
            duration_seconds=budget_stats["time"]["used_seconds"],
        )
        await emitter.commit_and_broadcast()

        logger.info(
            f"Run {run_id} completed successfully. "
            f"Budget used: {budget_stats['tokens']['used']} tokens, "
            f"${budget_stats['cost']['used']:.3f}, "
            f"{budget_stats['steps']['used']} steps, "
            f"{budget_stats['time']['used_seconds']:.1f}s"
        )

        # Clear token vault for this run
        self.policy_engine.clear_token_vault(run_id)

    async def _fail_run(self, run_id: str, error: dict, emitter: EventEmitter) -> None:
        """
        Mark run as failed and broadcast event.

        Args:
            run_id: Run identifier
            error: Error details
            emitter: Event emitter for broadcasting events
        """
        assert self.uow.runs is not None
        self.uow.runs.mark_failed(run_id, error)
        self.uow.commit()

        # Emit run failed event
        emitter.run_failed(
            error=error.get("message", "Unknown error"),
            error_type=error.get("type", "UnknownError"),
        )
        await emitter.commit_and_broadcast()

        logger.error(f"Run {run_id} failed: {error.get('message', 'Unknown error')}")

        # Clear token vault for this run
        self.policy_engine.clear_token_vault(run_id)

    def _get_current_step(self, run_id: str, step_id: str) -> Step:
        """Get current step entity from database using repository pattern"""
        assert self.uow.steps is not None
        step = self.uow.steps.get_by_name(run_id, step_id)
        if not step:
            raise ValueError(f"Step not found: {step_id}")
        return step

    def _resolve_secret(self, secret_name: str) -> str | None:
        """
        Resolve secret from credentials store.

        Args:
            secret_name: Credential name

        Returns:
            Secret value or None
        """
        try:
            import yaml
            from cryptography.fernet import Fernet

            assert self.uow.credentials is not None
            credential = self.uow.credentials.get(secret_name)
            if not credential:
                return None

            # Decrypt credential data
            key = settings.CREDENTIALS_ENCRYPTION_KEY
            cipher = Fernet(key.encode())

            decrypted = cipher.decrypt(credential.data_encrypted)
            data = yaml.safe_load(decrypted.decode())

            if isinstance(data, dict):
                # Extract first value from data dict (API key, token, etc.)
                return next(iter(data.values()), None)
            return str(data)

        except Exception as e:
            logger.warning(f"Failed to resolve secret '{secret_name}': {e}")
            return None
