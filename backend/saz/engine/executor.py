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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from saz.agents.critic import CriticAgent
from saz.agents.executor import ExecutorAgent
from saz.agents.planner_protocol import Planner
from saz.agents.schemas import (
    Critique,
    ErrorHandling,
    ExecutionPlan,
    PlanStep,
    UnknownStepTypeError,
    Verdict,
    WorkflowStructuralError,
)
from saz.audit.event_emitter import EventEmitter
from saz.db.models import Step
from saz.db.unit_of_work import UnitOfWork
from saz.engine.expressions import ConditionError, evaluate_condition, render_condition
from saz.engine.templating import TemplateContext
from saz.policies.policy_engine import PolicyEngine
from saz.security.redaction import redact_secret_values, redact_sensitive
from saz.settings import settings
from saz.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def derive_declared_tools(workflow_spec: dict[str, Any]) -> set[str]:
    """Compute the set of tools a workflow is allowed to ground.

    The allowlist is the union of an explicit ``workflow.allowed_tools`` list
    and the tools referenced by the declared steps (mirroring how the
    deterministic planner maps a step to its tool name). Returns an empty set
    when nothing constrains the workflow (e.g. an agentic workflow with no
    declared steps and no explicit allowlist).

    An empty set is NOT "allow everything": in agentic mode the runtime treats
    an empty declared set as deny-all (an agentic workflow that declares no
    tools may not ground any). See ``WorkflowExecutor._execute_tool_call``.
    """
    declared: set[str] = set()
    explicit = workflow_spec.get("allowed_tools") or []
    declared.update(t for t in explicit if isinstance(t, str))
    for step in workflow_spec.get("steps", []) or []:
        stype = step.get("type", "")
        if stype == "tool.call":
            tool = step.get("tool")
            if tool:
                declared.add(tool)
        elif stype.startswith("ai."):
            declared.add(stype)
        elif stype in {"artifact.store", "artifact.retrieve"}:
            declared.add(stype)
        elif stype == "webhook.wait":
            declared.add("webhook_wait")
        # condition / human.approval are control steps, not grounded tools.
    return declared


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


class RunSuspended(Exception):
    """Raised when a step suspends the run (human approval, webhook wait).

    This exception is used as a control-flow signal to stop the executor loop
    immediately after suspension is recorded. The run will only continue when
    an explicit resume or webhook callback occurs.
    """

    pass


# Maximum suspension duration when no timeout is declared. The runtime
# always records an absolute deadline so the SuspensionSweeper can reap
# stuck runs; unbounded suspensions are a memory + cost leak.
_DEFAULT_SUSPENSION_TIMEOUT_MINUTES = 1440  # 24h

# Minimum suspension duration. A YAML typo like ``timeout_minutes: 0.001``
# would otherwise produce a near-instant timeout the operator cannot
# realistically meet — and the SuspensionSweeper would reap the run before
# the human/external system even saw it. The floor matches the sweeper's
# default polling interval (60s), so anything below it is unenforceable.
_MIN_SUSPENSION_TIMEOUT_MINUTES = 1.0


_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_ARTIFACT_STORE_TYPES: dict[str, tuple[str, str]] = {
    "json": ("application/json", "json"),
    "text": ("text/plain", "txt"),
}


def _build_artifact_meta(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Derive download metadata for a stored artifact.

    Returns the on-disk ``blob_ref`` plus the ``content_type`` / ``filename`` /
    ``size_bytes`` the download API and UI need. Supports the two tools that
    produce downloadable files today: ``docx_render`` (binary .docx) and
    ``artifact.store`` (JSON/text).
    """
    name = result.get("name") or "artifact"
    if tool_name == "docx_render":
        return {
            "blob_ref": result.get("path") or "",
            "content_type": _DOCX_MIME,
            "filename": f"{name}.docx",
            "size_bytes": int(result.get("byte_size") or 0),
        }
    blob_ref = result.get("storage_path") or ""
    mime, ext = _ARTIFACT_STORE_TYPES.get(
        result.get("content_type", "json"), ("application/octet-stream", "bin")
    )
    size = 0
    if blob_ref:
        try:
            size = Path(blob_ref).stat().st_size
        except OSError:
            size = 0
    return {
        "blob_ref": blob_ref,
        "content_type": mime,
        "filename": f"{name}.{ext}",
        "size_bytes": size,
    }


def _unwrap_ai_output(tool_name: str, result: Any) -> Any:
    """Return the resolvable step output for a tool result.

    AI-op tools (``ai.*``) return their model fields wrapped in an envelope:
    ``{"output": <fields>, "usage": {...}, "metadata": {...}}``. The templating
    layer resolves ``$step('id').field`` against the stored step output
    directly, so the wrapped form makes every structured AI field reference
    resolve to empty (the field is one level too deep). Unwrap the envelope
    when the inner output is a structured object so the fields are directly
    addressable by ``$step('id').field``.

    Text-output ops (ai.generate/summarize/translate) keep the envelope: their
    content is a bare string, and ``Step.output`` (and the API/UI) is a JSON
    object, so unwrapping to a string would break the response contract. Their
    content stays reachable via ``$step('id').output``. Non-AI tools
    (http/webhook/artifact) are returned unchanged — already flat.
    """
    if (
        tool_name.startswith("ai.")
        and isinstance(result, dict)
        and "usage" in result
        and isinstance(result.get("output"), dict)
    ):
        return result["output"]
    return result


_APPROVAL_METADATA_FIELDS = ("title", "message", "payload", "approvers", "approver_role")


def _extract_approval_metadata(input_template: dict[str, Any] | None) -> dict[str, Any]:
    """Pull the human.approval DSL fields out of a step's params.

    Returns only the keys that were actually declared (non-None), so the
    approval event and suspension payload surface exactly what the YAML asked
    for instead of silently dropping ``title`` / ``message`` / ``payload`` /
    ``approvers`` / ``approver_role``.
    """
    params = input_template or {}
    return {k: params[k] for k in _APPROVAL_METADATA_FIELDS if params.get(k) is not None}


def _attach_timeout_metadata(
    error_payload: dict[str, Any], input_template: dict[str, Any] | None
) -> None:
    """Augment a suspension error payload with absolute timeout metadata.

    Reads ``timeout_minutes`` or ``timeout_seconds`` from the step's
    ``input_template`` (the DSL ``params`` block) and writes back:

    - ``suspended_at`` — ISO timestamp of when the run was suspended
    - ``timeout_at``   — ISO timestamp when the SuspensionSweeper should
      fail the run if no callback / resume has arrived

    Behaviour:

    - Missing / non-numeric / non-positive values fall back to
      ``_DEFAULT_SUSPENSION_TIMEOUT_MINUTES`` so the run still has a bound.
    - Positive values smaller than ``_MIN_SUSPENSION_TIMEOUT_MINUTES`` are
      clamped UP to that floor. A near-instant timeout would be reaped by
      the sweeper before any approver/callback could act, which is worse
      UX than a one-minute pause.
    """
    params = input_template or {}
    minutes: float | None = None
    if "timeout_minutes" in params:
        try:
            minutes = float(params["timeout_minutes"])
        except (TypeError, ValueError):
            minutes = None
    if minutes is None and "timeout_seconds" in params:
        try:
            minutes = float(params["timeout_seconds"]) / 60.0
        except (TypeError, ValueError):
            minutes = None
    if minutes is None or minutes <= 0:
        minutes = float(_DEFAULT_SUSPENSION_TIMEOUT_MINUTES)
    elif minutes < _MIN_SUSPENSION_TIMEOUT_MINUTES:
        minutes = _MIN_SUSPENSION_TIMEOUT_MINUTES

    now = datetime.now(UTC)
    deadline = now + timedelta(minutes=minutes)
    error_payload["suspended_at"] = now.isoformat()
    error_payload["timeout_at"] = deadline.isoformat()
    error_payload["timeout_minutes"] = minutes


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

        # Plaintext secret values resolved during this run, tracked so they can
        # be scrubbed from anything persisted, returned, or emitted.
        self._secret_values: set[str] = set()

        # Set secret resolver for executor agent
        self.executor_agent.secret_resolver = self._resolve_secret

        # Route planner/critic LLM spend to this run's budget so verification
        # and (re)planning count against budget_usd / token limits.
        self.critic.usage_recorder = self.policy_engine.record_llm_usage
        if hasattr(self.planner, "usage_recorder"):
            self.planner.usage_recorder = self.policy_engine.record_llm_usage

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

            # Bound the tools any plan may ground to the workflow's declared
            # set. Empty => unconstrained (full registry); warn so an
            # unbounded agentic workflow is visible.
            allowed_tools = derive_declared_tools(workflow_spec)
            if not allowed_tools and planner_mode == "agentic":
                logger.warning(
                    "agentic workflow %s declares no tools: grounded tool calls "
                    "will be denied. Declare workflow.allowed_tools (or tool.call "
                    "steps) to permit tools.",
                    run_id,
                )

            # Get PII policy from DSL (policies at root level in stored YAML)
            policies_dict = flow.definition.get("policies", {})
            # DSL uses pii.allow (boolean); convert to sanitizer mode string
            pii_allow = policies_dict.get("pii", {}).get("allow", False)
            pii_policy = "allow" if pii_allow else "redact"

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
                "emitter": emitter,
                "planner_mode": planner_mode,
                "allowed_tools": allowed_tools,
            }

            # Restore context from the latest attempt of each completed step.
            # When a run contains multiple attempts (from retry), only the
            # highest-attempt completed step per name is authoritative.
            if run.steps:
                # Group by step name, keeping only the latest attempt per name
                latest_by_name: dict[str, Any] = {}
                for step in run.steps:
                    existing = latest_by_name.get(step.name)
                    if existing is None or step.attempt > existing.attempt:
                        latest_by_name[step.name] = step

                for step in latest_by_name.values():
                    if step.status == "completed" and step.output:
                        # TemplateContext reads step_results[id]["output"] —
                        # see saz/engine/templating.py::_resolve_step_output.
                        # Store under that key so $step('name').field works
                        # after a resume/retry restore.
                        context["step_results"][step.name] = {"output": step.output}
                        context["completed_steps"].append(step.name)
                        logger.info(
                            f"Restored step result for '{step.name}' "
                            f"(attempt {step.attempt}) from previous execution"
                        )

            # Check if workflow exists
            if not workflow_spec:
                logger.warning(f"No workflow defined for flow {flow.id}")
                await self._complete_run(run_id, emitter)
                return

            # Budget gate before agentic planning. The agentic planner makes an
            # LLM call before any step runs, so a near-zero budget must stop it
            # here — otherwise the first planning call always bypasses the
            # budget. Deterministic planning is LLM-free and needs no pre-check.
            if planner_mode == "agentic":
                within_budget, budget_error = self.policy_engine.budget_tracker.check_budget(run_id)
                if not within_budget:
                    logger.error(
                        f"Budget exhausted before planning for run {run_id}: {budget_error}"
                    )
                    emitter.policy_budget_exhausted(
                        reason=budget_error or "budget exhausted before planning",
                        step_id=None,
                    )
                    await emitter.commit_and_broadcast()
                    await self._fail_run(
                        run_id,
                        {
                            "message": f"Budget exhausted before planning: {budget_error}",
                            "type": "BudgetExceededError",
                        },
                        emitter,
                    )
                    return

            # Generate execution plan
            plan = await self._generate_plan(
                workflow_spec=workflow_spec, run_id=run_id, context=context
            )

            logger.info(
                f"Generated plan with {len(plan.steps)} steps for run {run_id} "
                f"(estimated: ${plan.estimated_cost_usd:.3f}, {plan.estimated_time_seconds}s)"
            )

            # Emit plan generated event. Steps execute sequentially; PlanStep
            # has no dependency graph, so no "deps" field is emitted.
            steps_summary = [
                {
                    "id": step.step_id,
                    "intent": step.reasoning,
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
                # Skip steps already completed (e.g. when resuming after suspension)
                if plan_step.step_id in context["completed_steps"]:
                    logger.info(
                        f"Skipping already-completed step {plan_step.step_id} (resumed execution)"
                    )
                    continue

                # Check budget before each step
                within_budget, budget_error = self.policy_engine.budget_tracker.check_budget(run_id)
                if not within_budget:
                    logger.error(f"Budget exceeded for run {run_id}: {budget_error}")
                    emitter.policy_budget_exhausted(
                        reason=budget_error or "budget exceeded", step_id=plan_step.step_id
                    )
                    await emitter.commit_and_broadcast()
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

                # Optional `when` guard: a false guard skips the step entirely
                # — no grounding, no tool/model call, no side effects — and
                # records it as skipped (not completed) so downstream logic
                # never treats it as a successful result.
                try:
                    should_run, rendered_guard = self._evaluate_guard(plan_step, context)
                except WorkflowStructuralError as guard_error:
                    logger.error(f"Step {plan_step.step_id} guard error: {guard_error}")
                    await self._fail_run(
                        run_id,
                        {
                            "message": str(guard_error),
                            "type": type(guard_error).__name__,
                            "category": "structural",
                            "retryable": False,
                            "step": plan_step.step_id,
                            "step_number": step_number,
                        },
                        emitter,
                    )
                    return

                if not should_run:
                    assert self.uow.steps is not None
                    attempt = self.uow.steps.get_max_attempt(run_id, plan_step.step_id) + 1
                    skipped_step = self.uow.steps.append(
                        run_id=run_id,
                        number=step_number,
                        name=plan_step.step_id,
                        step_type=plan_step.step_type,
                        status="skipped",
                        attempt=attempt,
                    )
                    self.uow.commit()
                    emitter.step_skipped(
                        step_id=skipped_step.id,
                        step_name=plan_step.step_id,
                        condition=rendered_guard,
                    )
                    await emitter.commit_and_broadcast()
                    # Expose a skipped marker (NOT a success output) and mark the
                    # step handled so a resume does not re-run it.
                    context["step_results"][plan_step.step_id] = {"output": {"skipped": True}}
                    context["completed_steps"].append(plan_step.step_id)
                    logger.info(f"Step {plan_step.step_id} skipped (guard false): {rendered_guard}")
                    continue

                # Execute step
                try:
                    step_result = await self._execute_plan_step(
                        run_id=run_id, step_number=step_number, plan_step=plan_step, context=context
                    )

                    # Update context with step result. TemplateContext reads
                    # step_results[id]["output"] — wrap so $step(...) syntax
                    # resolves on subsequent steps.
                    context["step_results"][plan_step.step_id] = {"output": step_result}
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
                    # Policy violation - always fail immediately. The Step DB
                    # row was created by _execute_plan_step in "running" state
                    # and the inner retry loop's (PolicyViolation,
                    # EscalationRequired) clause re-raises without touching it.
                    # If we don't flip it to "failed" here, the row is stuck in
                    # "running" forever — which then makes
                    # StepRepository.get_first_failed_for_run() return None,
                    # and same-run retry blows up with "No failing step found".
                    current_step: Step | None = context.get("current_step")
                    if current_step is not None:
                        current_step.status = "failed"
                        current_step.end_ts = datetime.now(UTC)
                        if current_step.start_ts is not None:
                            start = (
                                current_step.start_ts
                                if current_step.start_ts.tzinfo
                                else current_step.start_ts.replace(tzinfo=UTC)
                            )
                            current_step.duration_ms = int(
                                (current_step.end_ts - start).total_seconds() * 1000
                            )
                        current_step.error = {
                            "message": str(step_error),
                            "type": "PolicyViolation",
                        }
                    error_dict = {
                        "message": str(step_error),
                        "type": "PolicyViolation",
                        "step": plan_step.step_id,
                        "step_number": step_number,
                    }
                    logger.error(f"Step {plan_step.step_id} blocked by policy: {step_error}")
                    await self._fail_run(run_id, error_dict, emitter)
                    return

                except WorkflowStructuralError as step_error:
                    # Permanent config/plan error (unknown tool/step type,
                    # missing args, unresolved template). Not retryable: mark the
                    # step failed and fail the run immediately. Mirrors the
                    # PolicyViolation path so the step row never sticks in
                    # "running".
                    current_step = context.get("current_step")
                    if current_step is not None:
                        current_step.status = "failed"
                        current_step.end_ts = datetime.now(UTC)
                        current_step.error = {
                            "message": str(step_error),
                            "type": type(step_error).__name__,
                        }
                    error_dict = {
                        "message": str(step_error),
                        "type": type(step_error).__name__,
                        "category": "structural",
                        "retryable": False,
                        "step": plan_step.step_id,
                        "step_number": step_number,
                    }
                    logger.error(f"Step {plan_step.step_id} structural error: {step_error}")
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
                    # Escalation required - suspend run.
                    # The Step DB record was created by _execute_plan_step and
                    # stashed on the context. Use its PK (not the YAML step
                    # name) when emitting events; events.step_id has an FK to
                    # steps.id, and passing the name violates that constraint
                    # under PostgreSQL. Also flip the step row to "suspended"
                    # so the UI doesn't keep showing it as still running.
                    current_step = context.get("current_step")
                    step_db_id = current_step.id if current_step else None
                    if current_step is not None:
                        current_step.status = "suspended"
                    callback_id = uuid4().hex
                    error_dict = {
                        "message": str(step_error),
                        "type": "EscalationRequired",
                        "step": plan_step.step_id,
                        "step_number": step_number,
                        "critique": step_error.critique.model_dump(),
                        "callback_id": callback_id,
                    }
                    _attach_timeout_metadata(error_dict, plan_step.input_template)
                    logger.warning(f"Step {plan_step.step_id} requires escalation: {step_error}")
                    self.uow.runs.mark_suspended(run_id, error_dict)
                    emitter.run_suspended(
                        reason=str(step_error),
                        step_id=step_db_id,
                    )
                    await emitter.commit_and_broadcast()
                    return

                except RunSuspended:
                    # Suspension step (human approval, webhook wait) has already
                    # recorded the suspension in the DB and emitted events.
                    # Stop the executor loop immediately.
                    logger.info(
                        f"Run {run_id} suspended at step {plan_step.step_id}, stopping executor"
                    )
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
                        # Route through proper suspension machinery. A bare
                        # mark_suspended leaves an unresumable run: no
                        # callback_id (so no webhook/resume can target it) and
                        # no timeout_at (so the SuspensionSweeper can never reap
                        # it). Attach both and emit run.suspended so the run is
                        # resumable and bounded. The step itself stays failed —
                        # it genuinely failed; the run is paused for a human
                        # decision (resume = same-run retry, or let it time out).
                        current_step = context.get("current_step")
                        step_db_id = current_step.id if current_step is not None else None
                        callback_id = uuid4().hex
                        error_dict["callback_id"] = callback_id
                        error_dict["type"] = "EscalationRequired"
                        _attach_timeout_metadata(error_dict, plan_step.input_template)
                        self.uow.runs.mark_suspended(run_id, error_dict)
                        emitter.run_suspended(
                            reason=f"Step {plan_step.step_id} escalated after failure",
                            step_id=step_db_id,
                        )
                        await emitter.commit_and_broadcast()
                        return

                    elif plan_step.error_handling == ErrorHandling.CONTINUE:
                        logger.warning(f"Step {plan_step.step_id} failed, continuing: {step_error}")
                        # Store error in step result under the standard
                        # ["output"] wrapper so $step('id').error templates
                        # in downstream steps still resolve.
                        context["step_results"][plan_step.step_id] = {
                            "output": {"error": error_dict}
                        }
                        context["completed_steps"].append(plan_step.step_id)
                        # A continued-on-fail step still consumed a step slot —
                        # count it so max_steps is not undercounted.
                        self.policy_engine.record_step(run_id)
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

        budget_dict = self._budget_dict(run_id)

        # Generate plan using injected planner (type chosen at construction)
        planner_mode = workflow_spec["planner_mode"]

        # In agentic mode only advertise the workflow's declared tools so the
        # planner never proposes a tool the runtime would deny. An empty
        # declared set advertises nothing (fail closed). Deterministic planning
        # ignores tool_registry for graph building, so leave it untouched.
        if planner_mode == "agentic":
            declared = context.get("allowed_tools") or set()
            tool_specs = [s for s in tool_specs if s.get("name") in declared]

        logger.info(
            f"Planning workflow for run {run_id} (mode: {planner_mode}, "
            f"steps: {len(workflow_spec.get('steps', []))})"
        )

        plan = await self.planner.plan(
            workflow_spec=workflow_spec,
            tool_registry=tool_specs,
            run_id=run_id,
            completed_steps=context.get("completed_steps", []),
            # Redact PII/secrets from run payload before it reaches the planner
            # LLM prompt (no-op for the deterministic planner, which ignores it).
            current_data=self._redact_pii_for_prompt(context.get("form_data", {})),
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

        # Create step record with the correct attempt number.
        # On first execution attempt=1. On retry, the run already contains
        # a failed step with the same name at attempt N; the new attempt
        # must be N+1 so historical attempts remain distinguishable.
        assert self.uow.steps is not None
        current_max_attempt = self.uow.steps.get_max_attempt(run_id, step_id)
        next_attempt = current_max_attempt + 1

        step = self.uow.steps.append(
            run_id=run_id,
            number=step_number,
            name=step_id,
            step_type=plan_step.step_type,
            status="running",
            attempt=next_attempt,
        )
        step.start_ts = datetime.now(UTC)
        self.uow.commit()

        # Store step record in context for use in tool calls
        context["current_step"] = step

        # Emit step started event (use step.id, not step_id which is the name)
        emitter.step_started(step_id=step.id, step_name=step_id, step_number=step_number)
        await emitter.commit_and_broadcast()

        # Execute with retries.
        # When a critique fails, store the feedback so the next retry can
        # include it in the AI-op instruction — this lets the model
        # self-correct instead of repeating the same mistake.
        max_attempts = plan_step.max_retries + 1
        last_error = None
        last_critique_feedback: str | None = None

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

                # If the previous attempt failed with critique feedback,
                # inject it into the context so _execute_step_action can
                # append it to the AI-op instruction.
                if last_critique_feedback:
                    context["_last_critique_feedback"] = last_critique_feedback
                else:
                    context.pop("_last_critique_feedback", None)

                # Execute step based on action type
                result = await self._execute_step_action(
                    plan_step=plan_step,
                    context=context,
                    run_id=run_id,
                    tool_attempt=attempt + 1,  # 1-based attempt ordinal
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
                step.output = self._redact_secrets(result)
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

            except RunSuspended:
                # Suspension is not a failure — let it propagate to the main loop
                raise

            except (PolicyViolation, EscalationRequired, WorkflowStructuralError):
                # Deterministic failures — retrying will not fix them.
                # PolicyViolation: PII on disallowed paths, budget exceeded, etc.
                # EscalationRequired: needs human review.
                # WorkflowStructuralError: unknown tool/step type, missing args,
                # unresolved template — permanent config/plan errors, fail fast.
                raise

            except Exception as e:
                last_error = e
                step.retry_count = attempt  # 0-based index of failed attempt
                self.uow.commit()
                logger.warning(f"Step {step_id} attempt {attempt + 1}/{max_attempts} failed: {e}")

                # Capture critique feedback for the next retry so the
                # AI-op prompt can include it for self-correction.
                if isinstance(e, CritiqueFailure):
                    last_critique_feedback = e.critique.reasoning
                else:
                    last_critique_feedback = None

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

    async def _execute_step_action(
        self,
        plan_step: PlanStep,
        context: dict,
        run_id: str,
        tool_attempt: int = 1,
    ) -> Any:
        """
        Execute step based on step_type.

        Args:
            plan_step: Plan step specification
            context: Execution context
            run_id: Run identifier
            tool_attempt: 1-based retry attempt ordinal (from the executor retry loop)

        Returns:
            Step result
        """
        t = plan_step.step_type

        # AI operations and tool.call → execute as tool call
        if t.startswith("ai.") or t == "tool.call" or t.startswith("artifact."):
            return await self._execute_tool_call(plan_step, context, run_id, tool_attempt)

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
            raise UnknownStepTypeError(
                f"Unknown step_type: {t!r}. "
                f"Expected: ai.*, tool.call, artifact.*, condition, human.approval, or webhook.wait"
            )

    async def _block_if_budget_exhausted(
        self, run_id: str, emitter: EventEmitter, step_id: str | None
    ) -> None:
        """Block before a verifier/critique LLM call when the budget is spent.

        The pre-execution policy check gates the *tool* call, but the verifier
        and critique are separate LLM calls and tool execution between them
        records cost. Re-checking here stops a single step from overshooting the
        cap by a full verifier/critique spend.
        """
        within_budget, reason = self.policy_engine.budget_tracker.check_budget(run_id)
        if within_budget:
            return
        emitter.policy_budget_exhausted(reason=reason or "budget exhausted", step_id=step_id)
        await emitter.commit_and_broadcast()
        raise PolicyViolation(f"Budget exceeded before LLM call: {reason}")

    async def _execute_tool_call(
        self,
        plan_step: PlanStep,
        context: dict,
        run_id: str,
        tool_attempt: int = 1,
    ) -> Any:
        """
        Execute tool call with dual-agent safety model:
        1. Ground step (ExecutorAgent)
        2. Policy check (PolicyEngine)
        3. Pre-execution verification (CriticAgent.verify_proposal)
           - If REPLAN: enter replanning loop (bounded by max_replan_attempts)
           - If REJECT/ESCALATE: block before execution
           - If APPROVE: proceed
        4. Execute tool (ToolRegistry)
        5. Redact output (PolicyEngine)
        6. Post-execution critique (CriticAgent.critique)
        7. Handle post-execution verdict

        Args:
            plan_step: Plan step with tool_name and input_template
            context: Execution context
            run_id: Run identifier

        Returns:
            Tool execution result

        Raises:
            PolicyViolation: If policy check fails
            CritiqueFailure: If verifier/critic returns FAIL verdict
            EscalationRequired: If verifier/critic returns ESCALATE verdict
            ReplanRequired: If replan attempts exhausted
        """
        emitter: EventEmitter = context["emitter"]
        planner_mode = context.get("planner_mode", "deterministic")
        tool_specs_dict = self.tool_registry.get_tool_specs_dict()
        # Bound tool selection to the workflow's declared tools. The declared
        # set is the union of workflow.allowed_tools and the tools referenced
        # by declared steps. This deterministic gate keeps a plan inside
        # workflow boundaries instead of trusting only the LLM verifier:
        #
        #   - declared non-empty    -> enforce membership against it
        #   - empty + agentic mode  -> fail closed: deny ALL grounded tools.
        #     An agentic workflow that declares no tools may not ground any;
        #     falling back to the full registry would let it call anything.
        #   - empty + deterministic -> no boundary needed; the plan IS the
        #     declared steps 1:1, so the grounded tool is whatever the step
        #     named (full registry, not enforced).
        declared = context.get("allowed_tools") or set()
        if declared:
            allowed_tool_names = sorted(declared)
            enforce_allowlist = True
        elif planner_mode == "agentic":
            allowed_tool_names = []
            enforce_allowlist = True
        else:
            allowed_tool_names = list(tool_specs_dict.keys())
            enforce_allowlist = False

        # --- Phase 1: Ground and verify with replan loop ---
        tool_call, step = await self._ground_and_verify(
            plan_step=plan_step,
            context=context,
            run_id=run_id,
            emitter=emitter,
            planner_mode=planner_mode,
            allowed_tool_names=allowed_tool_names,
            enforce_allowlist=enforce_allowlist,
            tool_specs_dict=tool_specs_dict,
        )

        # --- Phase 2: Apply PII transformations ---
        if self.policy_engine._is_model_tool(tool_call.tool):
            # Detect PII on the pre-tokenization arguments so the audit trail
            # records which paths were tokenized before the model call. The
            # paths are field names, not PII values, and emit() sanitizes the
            # payload anyway — so no raw PII is persisted.
            pii_paths = self.policy_engine.pii_detector.scan_dict(tool_call.arguments)
            tool_call.arguments = self.policy_engine.tokenize_arguments(
                tool_name=tool_call.tool,
                arguments=tool_call.arguments,
                run_id=run_id,
            )
            if pii_paths:
                emitter.policy_pii_redacted(
                    step_id=context["current_step"].id,
                    pii_stats={
                        "action": "tokenized",
                        "tool": tool_call.tool,
                        "paths": pii_paths,
                        "count": len(pii_paths),
                        "policy": "redact" if self.policy_engine.enforce_pii_redaction else "allow",
                    },
                )
                await emitter.commit_and_broadcast()
        elif self.policy_engine._is_outbound_tool(tool_call.tool):
            tool_call.arguments = self.policy_engine.detokenize_arguments(
                tool_name=tool_call.tool,
                arguments=tool_call.arguments,
                run_id=run_id,
            )

        # --- Phase 3: Execute tool ---
        current_step: Step = context["current_step"]

        emitter.tool_started(
            step_id=current_step.id,
            tool_name=tool_call.tool,
            attempt=tool_attempt,
        )
        await emitter.commit_and_broadcast()

        # For AI ops, inject the plan step's expected_output_schema so the
        # AI-op prompt builder lists the exact required field names and the
        # runtime validator enforces them.  Without this, ai.extract uses
        # its permissive default schema (additionalProperties: true) and
        # the model may return wrong key names that only the post-execution
        # critic catches — leading to repeated identical failures on retry.
        exec_arguments = {**tool_call.arguments}
        if tool_call.tool.startswith("ai."):
            # Inject the plan step's expected_output_schema so the AI-op
            # prompt builder lists exact field names and the validator
            # enforces them.
            if plan_step.expected_output_schema and "expected_schema" not in exec_arguments:
                exec_arguments["expected_schema"] = plan_step.expected_output_schema

            # Inject previous critique feedback so the model can
            # self-correct on retry instead of repeating the same error.
            critique_feedback = context.get("_last_critique_feedback")
            if critique_feedback and "instruction" in exec_arguments:
                exec_arguments["instruction"] = (
                    exec_arguments["instruction"]
                    + "\n\nPREVIOUS ATTEMPT FAILED. Fix this issue:\n"
                    + critique_feedback
                )

        tool_start_time = datetime.now()
        try:
            result = await self.tool_registry.execute_tool(
                tool_name=tool_call.tool,
                arguments=exec_arguments,
                idempotency_key=tool_call.idempotency_key,
                run_id=run_id,
                step_id=plan_step.step_id,
            )

            tool_duration_ms = int((datetime.now() - tool_start_time).total_seconds() * 1000)
            emitter.tool_succeeded(
                step_id=current_step.id,
                tool_name=tool_call.tool,
                duration_ms=tool_duration_ms,
                attempt=tool_attempt,
            )
            await emitter.commit_and_broadcast()

            # Persist Artifact row when artifact.store succeeds so the DB
            # reflects what the filesystem already does. The Artifact model
            # and run.artifacts relationship exist precisely for this — the
            # tool layer just writes a JSON blob, so without this hop the
            # database stays empty and any consumer of run.artifacts (read
            # repository, UI) sees nothing.
            if (
                tool_call.tool in ("artifact.store", "docx_render")
                and isinstance(result, dict)
                and result.get("artifact_id")
                and self.uow.artifacts is not None
            ):
                artifact_id = result["artifact_id"]
                artifact_name = result.get("name") or "artifact"
                art_meta = _build_artifact_meta(tool_call.tool, result)
                self.uow.artifacts.create(
                    run_id=run_id,
                    name=artifact_name,
                    blob_ref=art_meta["blob_ref"],
                    meta={
                        "artifact_id": artifact_id,
                        "content_type": art_meta["content_type"],
                        "filename": art_meta["filename"],
                        "size_bytes": art_meta["size_bytes"],
                    },
                    step_id=current_step.id,
                )
                self.uow.commit()
                emitter.artifact_created(
                    step_id=current_step.id,
                    artifact_id=str(artifact_id),
                    name=artifact_name,
                    content_type=art_meta["content_type"],
                )
                await emitter.commit_and_broadcast()

        except Exception as tool_error:
            tool_duration_ms = int((datetime.now() - tool_start_time).total_seconds() * 1000)
            emitter.tool_failed(
                step_id=current_step.id,
                tool_name=tool_call.tool,
                error=str(tool_error),
                error_type=type(tool_error).__name__,
                attempt=tool_attempt,
            )
            await emitter.commit_and_broadcast()
            raise

        # --- Phase 4: Record AI usage ---
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

        # --- Phase 5: Redact PII from output ---
        redacted_result = self.policy_engine.redact_output(
            data=result if isinstance(result, dict) else {"value": result},
            run_id=run_id,
        )

        # --- Phase 6: Post-execution critique ---
        # Tool execution above may have exhausted the budget; do not spend a
        # critique LLM call on top of it.
        await self._block_if_budget_exhausted(run_id, emitter, step.id)
        critique = await self.critic.critique(
            step=plan_step,
            tool_call={
                "tool": tool_call.tool,
                "arguments": self._redact_pii_for_prompt(tool_call.arguments),
            },
            result=redacted_result,
            run_id=run_id,
            completed_steps=context.get("completed_steps", []),
            current_state=self._redact_pii_for_prompt(context.get("step_results", {})),
        )

        step.critique = critique.model_dump()
        self.uow.commit()

        # Emit the post-execution critique verdict as a first-class audit event.
        emitter.critique_completed(
            step_id=step.id,
            verdict=critique.verdict.value,
            confidence=critique.confidence,
            reasoning=critique.reasoning,
        )
        await emitter.commit_and_broadcast()

        logger.info(
            "critique_received",
            extra={
                "run_id": run_id,
                "step_id": plan_step.step_id,
                "verdict": critique.verdict.value,
                "confidence": critique.confidence,
            },
        )

        # AI-op tools return their model fields wrapped as
        # ``{"output": <fields>, "usage": ..., "metadata": ...}`` (see
        # AIOperations). Downstream ``$step('id').field`` references resolve
        # against the step output directly, so expose the inner fields as the
        # step's resolvable output — otherwise every reference to an AI-op
        # field resolves to empty (the field lives one level too deep). Usage
        # and cost were already recorded above from the full envelope; whole
        # ``$step('id')`` references now embed the fields rather than the
        # usage/metadata envelope.
        resolvable_output = _unwrap_ai_output(tool_call.tool, redacted_result)

        # --- Phase 7: Handle post-execution verdict ---
        if critique.verdict == Verdict.PASS:
            return resolvable_output

        elif critique.verdict == Verdict.FAIL:
            raise CritiqueFailure(f"Critique failed: {critique.reasoning}", critique=critique)

        elif critique.verdict == Verdict.ESCALATE:
            raise EscalationRequired(
                f"Human approval required: {critique.reasoning}", critique=critique
            )

        elif critique.verdict == Verdict.REPLAN:
            # Post-execution replan: tool already ran but result is unsatisfactory.
            # This is a quality issue, not a safety issue. Fail the step.
            raise CritiqueFailure(
                f"Post-execution replan requested: {critique.reasoning}", critique=critique
            )

        return resolvable_output

    async def _ground_and_verify(
        self,
        plan_step: PlanStep,
        context: dict,
        run_id: str,
        emitter: EventEmitter,
        planner_mode: str,
        allowed_tool_names: list[str],
        enforce_allowlist: bool,
        tool_specs_dict: dict,
    ) -> tuple[Any, Step]:
        """
        Ground a step and run pre-execution verification with replan loop.

        Returns the verified tool_call and the step DB record.

        Raises:
            PolicyViolation: If policy check fails
            CritiqueFailure: If verifier rejects the proposal
            EscalationRequired: If verifier escalates to human
            ReplanRequired: If replan attempts exhausted
        """
        max_replan = self.policy_engine.max_replan_attempts
        replan_feedback: str | None = None

        for attempt in range(max_replan + 1):  # attempt 0 = original, 1..N = replans
            # Ground step
            tool_call = self.executor_agent.ground(
                step=plan_step,
                tool_registry=tool_specs_dict,
                current_data=context,
                run_id=run_id,
            )

            # Deterministic boundary: the grounded tool must be within the
            # workflow's declared/allowed tool set. This keeps an agentic plan
            # inside workflow boundaries regardless of the LLM verifier's
            # judgment. When enforce_allowlist is True an empty allowlist means
            # deny-all (agentic workflow declaring no tools). Not enforced in
            # deterministic mode, where the plan == declared steps.
            if enforce_allowlist and tool_call.tool not in allowed_tool_names:
                step = self._get_current_step(run_id, plan_step.step_id)
                if allowed_tool_names:
                    deny_reason = (
                        f"Agentic workflow attempted to use undeclared tool "
                        f"'{tool_call.tool}'. Declare it under "
                        f"workflow.allowed_tools. Allowed: {allowed_tool_names}"
                    )
                else:
                    deny_reason = (
                        f"Agentic workflow attempted to use tool '{tool_call.tool}' "
                        f"but declares no tools. Declare it under "
                        f"workflow.allowed_tools to permit it."
                    )
                step.policy_flags = {"blocked": True, "reason": deny_reason}
                self.uow.commit()
                emitter.policy_blocked(
                    step_id=step.id, tool_name=tool_call.tool, reason=deny_reason
                )
                await emitter.commit_and_broadcast()
                raise PolicyViolation(f"Tool call blocked: {deny_reason}")

            logger.info(
                "grounding_step",
                extra={
                    "run_id": run_id,
                    "step_id": plan_step.step_id,
                    "tool": tool_call.tool,
                    "attempt": attempt,
                },
            )

            # Store grounded input in step record. The persisted copy must
            # carry neither secrets nor (under pii.allow:false) raw PII; live
            # execution below still uses the real ``tool_call.arguments``.
            step = self._get_current_step(run_id, plan_step.step_id)
            step.input = {
                "tool": tool_call.tool,
                "arguments": self._redact_for_storage(tool_call.arguments),
            }
            self.uow.commit()

            # Policy check (before tokenization, to detect raw PII)
            allowed, reason = self.policy_engine.check_tool_call(
                tool_name=tool_call.tool,
                arguments=tool_call.arguments,
                run_id=run_id,
            )

            if not allowed:
                step.policy_flags = {"blocked": True, "reason": reason}
                self.uow.commit()
                # Emit a first-class, queryable safety event for the block. The
                # specific event type is derived from check_tool_call's reason
                # prefix so rate-limit / budget / PII blocks are distinguishable.
                reason_text = reason or "policy violation"
                if reason_text.startswith("Rate limit"):
                    emitter.policy_rate_limited(
                        tool_name=tool_call.tool, reason=reason_text, step_id=step.id
                    )
                elif reason_text.startswith("Budget exceeded"):
                    emitter.policy_budget_exhausted(reason=reason_text, step_id=step.id)
                else:
                    emitter.policy_blocked(
                        step_id=step.id, tool_name=tool_call.tool, reason=reason_text
                    )
                await emitter.commit_and_broadcast()
                raise PolicyViolation(f"Tool call blocked: {reason}")

            # Pre-execution verification — gate on budget so an exhausted run
            # does not spend a verifier LLM call.
            await self._block_if_budget_exhausted(run_id, emitter, step.id)
            verification = await self.critic.verify_proposal(
                step=plan_step,
                proposed_tool_call={
                    "tool": tool_call.tool,
                    "arguments": self._redact_pii_for_prompt(tool_call.arguments),
                },
                run_id=run_id,
                completed_steps=context.get("completed_steps", []),
                current_state=self._redact_pii_for_prompt(context.get("step_results", {})),
                allowed_tools=allowed_tool_names,
                planner_mode=planner_mode,
            )

            current_step: Step = context["current_step"]

            if verification.verdict == Verdict.PASS:
                # Approved — emit event and proceed to execution
                emitter.verifier_approved(
                    step_id=current_step.id,
                    tool_name=tool_call.tool,
                    confidence=verification.confidence,
                )
                await emitter.commit_and_broadcast()
                return tool_call, step

            elif verification.verdict == Verdict.FAIL:
                # Rejected — block before execution
                emitter.verifier_rejected(
                    step_id=current_step.id,
                    tool_name=tool_call.tool,
                    reasoning=verification.reasoning,
                )
                await emitter.commit_and_broadcast()
                raise CritiqueFailure(
                    f"Pre-execution verification failed: {verification.reasoning}",
                    critique=verification,
                )

            elif verification.verdict == Verdict.ESCALATE:
                # Escalate — block and suspend for human review
                emitter.verifier_escalated(
                    step_id=current_step.id,
                    tool_name=tool_call.tool,
                    reasoning=verification.reasoning,
                )
                await emitter.commit_and_broadcast()
                raise EscalationRequired(
                    f"Pre-execution escalation: {verification.reasoning}",
                    critique=verification,
                )

            elif verification.verdict == Verdict.REPLAN:
                # Replan requested — check if we have attempts remaining
                if attempt >= max_replan:
                    # Exhausted all replan attempts
                    emitter.replan_exhausted(
                        step_id=current_step.id,
                        max_attempts=max_replan,
                        final_verdict="replan",
                    )
                    await emitter.commit_and_broadcast()
                    raise ReplanRequired(
                        f"Replan attempts exhausted ({max_replan}): {verification.reasoning}",
                        critique=verification,
                    )

                # Emit replan events
                emitter.verifier_replan_requested(
                    step_id=current_step.id,
                    tool_name=tool_call.tool,
                    reasoning=verification.reasoning,
                    attempt=attempt + 1,
                )

                replan_feedback = verification.reasoning
                modifications = verification.suggestions.get("modifications", "")
                if modifications:
                    replan_feedback += f" Suggested modifications: {modifications}"

                emitter.replan_attempted(
                    step_id=current_step.id,
                    attempt=attempt + 1,
                    max_attempts=max_replan,
                    feedback=replan_feedback,
                )
                await emitter.commit_and_broadcast()

                # In agentic mode: ask planner to revise the step
                # In deterministic mode: can't change the plan, so treat as failure
                if planner_mode == "deterministic":
                    raise ReplanRequired(
                        f"Verifier requested replan but mode is deterministic: "
                        f"{verification.reasoning}",
                        critique=verification,
                    )

                # Ask planner to produce a revised step
                logger.info(
                    f"Replanning step {plan_step.step_id} (attempt {attempt + 1}/{max_replan})"
                )

                # Advertise only the workflow's declared tools, exactly as the
                # initial plan does, so the replanner never proposes a tool the
                # runtime would deny (which would waste a replan attempt).
                declared = context.get("allowed_tools") or set()
                replan_tool_specs = [
                    s for s in self.tool_registry.get_tool_specs() if s.get("name") in declared
                ]

                # Re-plan: give the planner the feedback and ask for a revised approach
                revised_plan = await self.planner.plan(
                    workflow_spec={
                        "name": "replan",
                        "planner_mode": "agentic",
                        "steps": [
                            {
                                "id": plan_step.step_id,
                                "type": plan_step.step_type,
                                "instruction": plan_step.reasoning,
                                "description": f"REPLAN: {replan_feedback}",
                            }
                        ],
                    },
                    tool_registry=replan_tool_specs,
                    run_id=run_id,
                    completed_steps=context.get("completed_steps", []),
                    current_data=self._redact_pii_for_prompt(context.get("form_data", {})),
                    budget=self._budget_dict(run_id),
                )

                if revised_plan.steps:
                    # Use the revised step for the next iteration
                    plan_step = revised_plan.steps[0]

                    emitter.replan_succeeded(
                        step_id=current_step.id,
                        attempt=attempt + 1,
                    )
                    await emitter.commit_and_broadcast()
                else:
                    raise ReplanRequired(
                        f"Planner produced empty replan: {replan_feedback}",
                        critique=verification,
                    )

                # Budget check after replan (replanning uses tokens)
                within_budget, budget_error = self.policy_engine.budget_tracker.check_budget(run_id)
                if not within_budget:
                    raise PolicyViolation(f"Budget exceeded during replanning: {budget_error}")

        # Should not reach here
        raise ReplanRequired(
            "Replan loop exited without resolution",
            critique=Critique(
                verdict=Verdict.REPLAN,
                reasoning="Internal error: replan loop exited unexpectedly",
                issues=[],
                safety_flags=[],
                suggestions={},
                confidence=0.0,
            ),
        )

    async def _execute_condition(self, plan_step: PlanStep, context: dict) -> Any:
        """
        Evaluate a conditional expression.

        Args:
            plan_step: Plan step with condition expression
            context: Execution context

        Returns:
            Boolean result
        """
        condition_expr = plan_step.input_template.get("condition", "true")

        template_context = TemplateContext(
            form_data=context["form_data"],
            step_results=context["step_results"],
            secret_resolver=self._resolve_secret,
        )

        def resolve_ref(token: str) -> Any:
            return template_context.resolve("{{ " + token + " }}")

        try:
            result = evaluate_condition(condition_expr, resolve_ref)
            resolved_condition = render_condition(condition_expr, resolve_ref)
        except ConditionError as exc:
            raise ValueError(f"Invalid condition expression: {exc}") from exc

        logger.info(f"Condition '{condition_expr}' evaluated to {result}")

        return {"result": result, "condition": resolved_condition}

    def _evaluate_guard(self, plan_step: PlanStep, context: dict) -> tuple[bool, str]:
        """Evaluate a step's optional ``when`` guard.

        Returns ``(should_run, rendered_condition)``. A step with no guard
        always runs. A guard expression that cannot be evaluated is a
        structural error (raised), so a malformed guard fails closed rather
        than silently running the step.
        """
        guard_expr = plan_step.guard
        if not guard_expr:
            return True, ""

        template_context = TemplateContext(
            form_data=context["form_data"],
            step_results=context["step_results"],
            secret_resolver=self._resolve_secret,
        )

        def resolve_ref(token: str) -> Any:
            return template_context.resolve("{{ " + token + " }}")

        try:
            result = evaluate_condition(guard_expr, resolve_ref)
            rendered = render_condition(guard_expr, resolve_ref)
        except ConditionError as exc:
            raise WorkflowStructuralError(
                f"Invalid `when` guard on step {plan_step.step_id}: {exc}"
            ) from exc
        return bool(result), rendered

    async def _execute_human_approval(self, plan_step: PlanStep, context: dict, run_id: str) -> Any:
        """
        Suspend run for human approval.

        Generates a callback_id for webhook-based resumption and emits
        APPROVAL_REQUESTED and RUN_SUSPENDED events, then raises RunSuspended
        to stop the executor loop immediately.

        Args:
            plan_step: Plan step
            context: Execution context
            run_id: Run identifier

        Raises:
            RunSuspended: Always raised to stop the executor loop.
        """
        logger.info(f"Step {plan_step.step_id} requires human approval")

        emitter: EventEmitter = context["emitter"]
        current_step: Step | None = context.get("current_step")
        step_db_id = current_step.id if current_step else None

        # Generate callback_id for webhook-based resumption
        callback_id = uuid4().hex

        # Surface the approval DSL fields instead of silently dropping them.
        # title/message/payload are display/routing metadata; approvers is an
        # allowlist enforced on the authenticated /resume path (see
        # webhooks.resume_run). approver_role is routing metadata only — Saz
        # has no role system, so it is surfaced but not enforced. The raw
        # webhook callback URL remains a capability: possessing the callback_id
        # authorizes resume regardless of approvers.
        approval_meta = _extract_approval_metadata(plan_step.input_template)

        # Emit approval requested event (payload is sanitized by the emitter).
        emitter.approval_requested(
            step_id=step_db_id,
            step_name=plan_step.step_id,
            reasoning=plan_step.reasoning,
            callback_id=callback_id,
            **approval_meta,
        )

        # Mark the step as suspended (not completed — it is still waiting)
        if current_step:
            current_step.status = "suspended"

        # Emit step-level suspension event (run-level emitted below).
        emitter.step_suspended(
            step_id=step_db_id,
            step_name=plan_step.step_id,
            reason="awaiting_human_approval",
        )

        # Suspend run with callback_id for webhook lookup
        assert self.uow.runs is not None
        error_payload: dict[str, Any] = {
            "message": f"Human approval required for step {plan_step.step_id}",
            "type": "HumanApprovalRequired",
            "step_id": plan_step.step_id,
            "reasoning": plan_step.reasoning,
            "callback_id": callback_id,
        }
        # Persist approval routing metadata so the authenticated /resume path
        # can enforce the approvers allowlist and the UI can display it.
        if approval_meta:
            error_payload["approval"] = approval_meta
        _attach_timeout_metadata(error_payload, plan_step.input_template)
        self.uow.runs.mark_suspended(run_id, error_payload)

        # Emit run suspended event
        emitter.run_suspended(
            reason=f"Awaiting human approval for step {plan_step.step_id}",
            step_id=step_db_id,
        )
        await emitter.commit_and_broadcast()

        raise RunSuspended(f"Awaiting human approval for step {plan_step.step_id}")

    async def _execute_webhook_wait(self, plan_step: PlanStep, context: dict, run_id: str) -> Any:
        """
        Suspend run while waiting for a webhook callback.

        Generates a callback_id, marks the run as suspended, emits events,
        and raises RunSuspended to stop the executor loop.

        Args:
            plan_step: Plan step
            context: Execution context
            run_id: Run identifier

        Raises:
            RunSuspended: Always raised to stop the executor loop.
        """
        logger.info(f"Step {plan_step.step_id} waiting for webhook callback")

        emitter: EventEmitter = context["emitter"]
        current_step: Step | None = context.get("current_step")
        step_db_id = current_step.id if current_step else None

        # Generate callback_id for webhook lookup
        callback_id = uuid4().hex

        # Mark the step as suspended
        if current_step:
            current_step.status = "suspended"

        # Emit step-level suspension event (run-level emitted below).
        emitter.step_suspended(
            step_id=step_db_id,
            step_name=plan_step.step_id,
            reason="awaiting_webhook_callback",
        )

        # Suspend run with callback_id and the expected event name. The event
        # name is a compile-time-required field on webhook.wait; persisting it
        # lets the callback handler reject a mismatched callback instead of
        # resuming on any callback to the URL.
        assert self.uow.runs is not None
        error_payload: dict[str, Any] = {
            "message": f"Webhook wait for step {plan_step.step_id}",
            "type": "WebhookWait",
            "step_id": plan_step.step_id,
            "callback_id": callback_id,
        }
        expected_event = (plan_step.input_template or {}).get("event_name")
        if expected_event:
            error_payload["event_name"] = expected_event
        _attach_timeout_metadata(error_payload, plan_step.input_template)
        self.uow.runs.mark_suspended(run_id, error_payload)

        # Emit run suspended event
        emitter.run_suspended(
            reason=f"Waiting for webhook callback for step {plan_step.step_id}",
            step_id=step_db_id,
        )
        await emitter.commit_and_broadcast()

        raise RunSuspended(f"Waiting for webhook callback for step {plan_step.step_id}")

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

    def _budget_dict(self, run_id: str) -> dict[str, Any]:
        """Flattened budget shape the planner prompt expects."""
        remaining = self.policy_engine.get_budget_status(run_id)
        tracker = self.policy_engine.budget_tracker
        return {
            "remaining_tokens": remaining["tokens"]["remaining"],
            "max_tokens": tracker.max_tokens,
            "remaining_cost": remaining["cost"]["remaining"],
            "max_cost_usd": tracker.max_cost_usd,
            "remaining_steps": remaining["steps"]["remaining"],
            "max_steps": tracker.max_steps,
        }

    def _redact_secrets(self, obj: Any) -> Any:
        """Scrub resolved secret values from anything persisted or returned."""
        return redact_secret_values(obj, self._secret_values)

    def _redact_for_storage(self, obj: Any) -> Any:
        """Scrub secrets, then PII (when policy enforces), for persisted columns.

        Mirrors :meth:`_redact_pii_for_prompt` but keeps the existing secret
        scrubbing (resolved ``$secret(...)`` values) rather than the broader
        prompt redaction, so persisted ``step.input`` stays faithful to the
        real arguments apart from the values that must never be stored.
        """
        scrubbed = self._redact_secrets(obj)
        if not self.policy_engine.enforce_pii_redaction:
            return scrubbed
        if isinstance(scrubbed, dict):
            return self.policy_engine.pii_detector.redact_dict(scrubbed)
        # Wrap non-dicts so the recursive dict redactor can reach nested strings.
        return self.policy_engine.pii_detector.redact_dict({"_": scrubbed})["_"]

    def _redact_for_prompt(self, obj: Any) -> Any:
        """Redact secrets before sending tool arguments to the verifier/critic LLM.

        Combines sensitive-key redaction with known resolved secret-value
        scrubbing so neither ``$secret(...)`` values nor credential-named
        fields ever reach an LLM provider.
        """
        return redact_sensitive(obj, self._secret_values)

    def _redact_pii_for_prompt(self, obj: Any) -> Any:
        """Scrub PII and secrets from data before it reaches an LLM prompt.

        Planner, verifier, and critic prompts are built from the run payload,
        step history, and tool arguments — any of which may carry PII. We
        redact (mask) rather than tokenize because prompt content is never
        detokenized, and masking preserves enough structure for the model to
        reason about which fields are present.

        Secrets/credentials are always scrubbed. PII is additionally redacted
        when the run's PII policy enforces redaction (``pii.allow: false``,
        the default). When the operator sets ``pii.allow: true`` they have
        opted into PII flow, so only secrets are scrubbed here.
        """
        scrubbed = self._redact_for_prompt(obj)
        if not self.policy_engine.enforce_pii_redaction:
            return scrubbed
        if isinstance(scrubbed, dict):
            return self.policy_engine.pii_detector.redact_dict(scrubbed)
        # Wrap non-dicts so the recursive dict redactor can reach nested strings.
        return self.policy_engine.pii_detector.redact_dict({"_": scrubbed})["_"]

    def _resolve_secret(self, secret_name: str) -> str | None:
        """
        Resolve secret from credentials store.

        Args:
            secret_name: Credential name

        Returns:
            Secret value or None
        """
        import yaml
        from cryptography.fernet import Fernet

        assert self.uow.credentials is not None
        credential = self.uow.credentials.get(secret_name)
        if not credential:
            # Missing credential: return None so the templating layer raises a
            # clear "Secret '<name>' not found" at the point of use. This is the
            # only swallowed case — and it is not silent (the caller raises).
            logger.warning("secret_not_found name=%s", secret_name)
            return None

        # Decryption / config failures must NOT silently degrade to "no secret"
        # (which would let a step run with a missing credential). Fail loudly —
        # but never log or embed the key or ciphertext in the error.
        key = settings.CREDENTIALS_ENCRYPTION_KEY
        try:
            cipher = Fernet(key.encode())
            decrypted = cipher.decrypt(credential.data_encrypted)
            data = yaml.safe_load(decrypted.decode())
        except Exception as e:
            raise WorkflowStructuralError(
                f"Failed to decrypt credential '{secret_name}': check the "
                f"CREDENTIALS_ENCRYPTION_KEY configuration ({type(e).__name__})"
            ) from None

        if isinstance(data, dict):
            # Deterministic contract: one value per credential. A multi-key blob
            # is ambiguous for $secret(name) — fail loudly rather than guessing.
            if len(data) == 1:
                value = next(iter(data.values()))
            elif len(data) == 0:
                value = None
            else:
                raise WorkflowStructuralError(
                    f"Credential '{secret_name}' stores multiple keys "
                    f"({sorted(data)}); $secret() resolves a single value. "
                    f"Store one value per credential."
                )
        else:
            value = str(data)

        if isinstance(value, str) and value:
            self._secret_values.add(value)
        return value
