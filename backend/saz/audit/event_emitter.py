"""Helper functions for emitting audit events from the engine."""

from datetime import UTC, datetime
from typing import Any

from saz.audit.event_bus import event_bus
from saz.audit.sanitizer import AuditSanitizer
from saz.db.unit_of_work import UnitOfWork
from saz.domain.event_schema import Event, EventType
from saz.domain.literals import Actor, PlannerMode, Severity


class EventEmitter:
    """
    Helper class for emitting audit events from workflow execution.

    Simplifies event creation and ensures consistent patterns.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        run_id: str,
        planner_mode: PlannerMode | str,
        pii_policy: str = "redact",
        actor_user_id: str | None = None,
    ):
        """
        Args:
            actor_user_id: When set, every event emitted with ``actor="user"``
                is automatically attributed to this user id. System and LLM
                events ignore it. Pass the authenticated user's id from the
                route layer so retry/resume/approval events carry attribution
                without each call site having to remember.
        """
        self.uow = uow
        self.run_id = run_id
        self.planner_mode = PlannerMode(planner_mode)
        self.sanitizer = AuditSanitizer()
        self.pii_policy = pii_policy
        self.actor_user_id = actor_user_id

    def emit(
        self,
        event_type: EventType,
        summary: str,
        payload: dict[str, Any] | None = None,
        step_id: str | None = None,
        correlation_id: str | None = None,
        severity: Severity | str = Severity.INFO,
        actor: Actor | str = Actor.SYSTEM,
        tags: dict[str, str] | None = None,
        actor_user_id: str | None = None,
    ) -> None:
        """
        Emit an audit event.

        Args:
            event_type: Type of event
            summary: Human-readable summary
            payload: Event-specific data
            step_id: Optional step ID
            correlation_id: Optional correlation ID for tracing
            severity: Event severity (info, warn, error)
            actor: Who triggered the event (system, user, llm)
            tags: Additional tags for filtering
            actor_user_id: Overrides the emitter-level default user id for
                this single event. Only meaningful when ``actor == "user"``.
        """
        # Sanitize payload AND the human-readable summary. The summary is built
        # by interpolating error text, LLM reasoning, and exception messages, so
        # it can leak the same PII/secrets the payload redactor strips — it must
        # not be a bypass around the sanitizer.
        sanitized_payload = self.sanitizer.redact_payload(payload or {}, self.pii_policy)
        sanitized_summary = self.sanitizer.redact_text(summary, self.pii_policy)

        actor_value = Actor(actor)

        # Only attribute to a user when the event is actually a user action.
        resolved_user_id = (
            (actor_user_id if actor_user_id is not None else self.actor_user_id)
            if actor_value is Actor.USER
            else None
        )

        event = Event(
            event_type=event_type,
            run_id=self.run_id,
            step_id=step_id,
            correlation_id=correlation_id,
            planner_mode=self.planner_mode,
            severity=Severity(severity),
            actor=actor_value,
            actor_user_id=resolved_user_id,
            summary=sanitized_summary,
            payload=sanitized_payload,
            tags=tags or {},
            timestamp=datetime.now(UTC),
        )

        self.uow.emit_event(event)

    async def commit_and_broadcast(self) -> None:
        """Commit events to DB and broadcast to WebSocket clients."""
        emitted_events = self.uow.commit()
        await event_bus.publish(emitted_events)

    # Convenience methods for common event types

    def run_started(self, flow_id: str, flow_name: str, **kwargs) -> None:
        """Emit run.started event."""
        self.emit(
            EventType.RUN_STARTED,
            f"Run started: {flow_name}",
            payload={"flow_id": flow_id, "flow_name": flow_name, **kwargs},
            tags={"flow": flow_id},
        )

    def run_completed(self, **kwargs) -> None:
        """Emit run.completed event."""
        self.emit(
            EventType.RUN_COMPLETED,
            "Run completed successfully",
            payload={"status": "completed", **kwargs},
        )

    def run_failed(self, error: str, error_type: str, **kwargs) -> None:
        """Emit run.failed event."""
        self.emit(
            EventType.RUN_FAILED,
            f"Run failed: {error}",
            payload={"error": error, "error_type": error_type, **kwargs},
            severity="error",
        )

    def step_started(self, step_id: str, step_name: str, step_number: int, **kwargs) -> None:
        """Emit step.started event."""
        self.emit(
            EventType.STEP_STARTED,
            f"Step started: {step_name}",
            payload={
                "step_name": step_name,
                "step_number": step_number,
                **kwargs,
            },
            step_id=step_id,
        )

    def step_completed(self, step_id: str, step_name: str, duration_ms: int, **kwargs) -> None:
        """Emit step.completed event."""
        self.emit(
            EventType.STEP_COMPLETED,
            f"Step completed: {step_name}",
            payload={
                "step_name": step_name,
                "duration_ms": duration_ms,
                **kwargs,
            },
            step_id=step_id,
        )

    def step_failed(
        self, step_id: str, step_name: str, error: str, error_type: str, **kwargs
    ) -> None:
        """Emit step.failed event."""
        self.emit(
            EventType.STEP_FAILED,
            f"Step failed: {step_name} - {error}",
            payload={
                "step_name": step_name,
                "error": error,
                "error_type": error_type,
                **kwargs,
            },
            step_id=step_id,
            severity="error",
        )

    def tool_started(self, step_id: str, tool_name: str, attempt: int = 1, **kwargs) -> None:
        """Emit tool.started event."""
        self.emit(
            EventType.TOOL_STARTED,
            f"Tool started: {tool_name} (attempt {attempt})",
            payload={"tool": tool_name, "attempt": attempt, **kwargs},
            step_id=step_id,
        )

    def tool_succeeded(self, step_id: str, tool_name: str, duration_ms: int, **kwargs) -> None:
        """Emit tool.succeeded event."""
        self.emit(
            EventType.TOOL_SUCCEEDED,
            f"Tool succeeded: {tool_name}",
            payload={
                "tool": tool_name,
                "duration_ms": duration_ms,
                **kwargs,
            },
            step_id=step_id,
        )

    def tool_failed(
        self, step_id: str, tool_name: str, error: str, error_type: str, **kwargs
    ) -> None:
        """Emit tool.failed event."""
        self.emit(
            EventType.TOOL_FAILED,
            f"Tool failed: {tool_name} - {error}",
            payload={
                "tool": tool_name,
                "error": error,
                "error_type": error_type,
                **kwargs,
            },
            step_id=step_id,
            severity="error",
        )

    def plan_generated(
        self, total_steps: int, steps: list[dict], estimated_cost: float = 0.0, **kwargs
    ) -> None:
        """Emit plan.generated event."""
        self.emit(
            EventType.PLAN_GENERATED,
            f"Execution plan generated with {total_steps} steps",
            payload={
                "total_steps": total_steps,
                "steps": steps,
                "estimated_cost_usd": estimated_cost,
                **kwargs,
            },
            actor="llm" if self.planner_mode == "agentic" else "system",
        )

    def policy_pii_redacted(self, step_id: str, pii_stats: dict, **kwargs) -> None:
        """Emit policy.pii.redacted event."""
        self.emit(
            EventType.POLICY_PII_REDACTED,
            f"PII redacted: {pii_stats.get('total', 0)} items",
            payload={"pii_stats": pii_stats, **kwargs},
            step_id=step_id,
            severity="warn",
        )

    def policy_budget_updated(
        self, tokens_used: int, cost_usd: float, budget_remaining_usd: float, **kwargs
    ) -> None:
        """Emit policy.budget.updated event."""
        self.emit(
            EventType.POLICY_BUDGET_UPDATED,
            f"Budget updated: ${cost_usd:.4f} spent, ${budget_remaining_usd:.4f} remaining",
            payload={
                "tokens_used": tokens_used,
                "cost_usd": cost_usd,
                "budget_remaining_usd": budget_remaining_usd,
                **kwargs,
            },
        )

    def policy_blocked(self, step_id: str | None, tool_name: str, reason: str, **kwargs) -> None:
        """Emit policy.blocked event when a tool call is denied by policy."""
        self.emit(
            EventType.POLICY_BLOCKED,
            f"Policy blocked tool call: {tool_name} - {reason}",
            payload={"tool": tool_name, "reason": reason, **kwargs},
            step_id=step_id,
            severity="error",
        )

    def policy_budget_exhausted(self, reason: str, step_id: str | None = None, **kwargs) -> None:
        """Emit policy.budget.exhausted event when a run hits a budget cap."""
        self.emit(
            EventType.POLICY_BUDGET_EXHAUSTED,
            f"Budget exhausted: {reason}",
            payload={"reason": reason, **kwargs},
            step_id=step_id,
            severity="error",
        )

    def policy_rate_limited(
        self, tool_name: str, reason: str, step_id: str | None = None, **kwargs
    ) -> None:
        """Emit policy.rate_limited event when a tool call hits a rate limit."""
        self.emit(
            EventType.POLICY_RATE_LIMITED,
            f"Rate limit hit for {tool_name}: {reason}",
            payload={"tool": tool_name, "reason": reason, **kwargs},
            step_id=step_id,
            severity="warn",
        )

    def usage_recorded(
        self,
        step_id: str | None,
        tokens: int,
        cost_usd: float,
        duration_ms: int = 0,
        model: str = "unknown",
        **kwargs,
    ) -> None:
        """Emit usage.recorded event."""
        self.emit(
            EventType.USAGE_RECORDED,
            f"Consumed {tokens:,} tokens (${cost_usd:.4f})",
            payload={
                "tokens": tokens,
                "cost_usd": cost_usd,
                "duration_ms": duration_ms,
                "model": model,
                **kwargs,
            },
            step_id=step_id,
        )

    def progress_updated(self, completed: int, total: int, percent: float, **kwargs) -> None:
        """Emit progress.updated event."""
        self.emit(
            EventType.PROGRESS_UPDATED,
            f"Progress: {completed}/{total} steps ({percent:.0f}%)",
            payload={
                "completed": completed,
                "total": total,
                "percent": percent,
                **kwargs,
            },
        )

    # --- Verifier events (pre-execution) ---

    def verifier_approved(self, step_id: str, tool_name: str, confidence: float, **kwargs) -> None:
        """Emit verifier.approved event."""
        self.emit(
            EventType.VERIFIER_APPROVED,
            f"Verifier approved: {tool_name}",
            payload={"tool": tool_name, "confidence": confidence, **kwargs},
            step_id=step_id,
            actor="llm",
        )

    def verifier_rejected(self, step_id: str, tool_name: str, reasoning: str, **kwargs) -> None:
        """Emit verifier.rejected event."""
        self.emit(
            EventType.VERIFIER_REJECTED,
            f"Verifier rejected: {tool_name} - {reasoning}",
            payload={"tool": tool_name, "reasoning": reasoning, **kwargs},
            step_id=step_id,
            severity="error",
            actor="llm",
        )

    def verifier_replan_requested(
        self, step_id: str, tool_name: str, reasoning: str, attempt: int, **kwargs
    ) -> None:
        """Emit verifier.replan_requested event."""
        self.emit(
            EventType.VERIFIER_REPLAN_REQUESTED,
            f"Verifier requested replan for {tool_name} (attempt {attempt})",
            payload={
                "tool": tool_name,
                "reasoning": reasoning,
                "attempt": attempt,
                **kwargs,
            },
            step_id=step_id,
            severity="warn",
            actor="llm",
        )

    def verifier_escalated(self, step_id: str, tool_name: str, reasoning: str, **kwargs) -> None:
        """Emit verifier.escalated event."""
        self.emit(
            EventType.VERIFIER_ESCALATED,
            f"Verifier escalated: {tool_name} - {reasoning}",
            payload={"tool": tool_name, "reasoning": reasoning, **kwargs},
            step_id=step_id,
            severity="warn",
            actor="llm",
        )

    # --- Replanning events ---

    def replan_attempted(
        self, step_id: str, attempt: int, max_attempts: int, feedback: str, **kwargs
    ) -> None:
        """Emit replan.attempted event."""
        self.emit(
            EventType.REPLAN_ATTEMPTED,
            f"Replan attempt {attempt}/{max_attempts}",
            payload={
                "attempt": attempt,
                "max_attempts": max_attempts,
                "feedback": feedback,
                **kwargs,
            },
            step_id=step_id,
            actor="llm",
        )

    def replan_succeeded(self, step_id: str, attempt: int, **kwargs) -> None:
        """Emit replan.succeeded event."""
        self.emit(
            EventType.REPLAN_SUCCEEDED,
            f"Replan succeeded on attempt {attempt}",
            payload={"attempt": attempt, **kwargs},
            step_id=step_id,
            actor="llm",
        )

    def replan_exhausted(
        self, step_id: str, max_attempts: int, final_verdict: str, **kwargs
    ) -> None:
        """Emit replan.exhausted event."""
        self.emit(
            EventType.REPLAN_EXHAUSTED,
            f"Replan exhausted after {max_attempts} attempts (final: {final_verdict})",
            payload={
                "max_attempts": max_attempts,
                "final_verdict": final_verdict,
                **kwargs,
            },
            step_id=step_id,
            severity="error",
            actor="llm",
        )

    # --- Approval events ---

    def approval_requested(
        self,
        step_id: str | None,
        step_name: str,
        reasoning: str,
        callback_id: str | None = None,
        **kwargs,
    ) -> None:
        """Emit approval.requested event."""
        self.emit(
            EventType.APPROVAL_REQUESTED,
            f"Approval requested for step: {step_name}",
            payload={
                "step_name": step_name,
                "reasoning": reasoning,
                "callback_id": callback_id,
                **kwargs,
            },
            step_id=step_id,
        )

    def approval_granted(self, step_id: str | None, step_name: str, **kwargs) -> None:
        """Emit approval.granted event."""
        self.emit(
            EventType.APPROVAL_GRANTED,
            f"Approval granted for step: {step_name}",
            payload={"step_name": step_name, **kwargs},
            step_id=step_id,
            actor="user",
        )

    def approval_denied(
        self, step_id: str | None, step_name: str, reason: str = "", **kwargs
    ) -> None:
        """Emit approval.denied event."""
        self.emit(
            EventType.APPROVAL_DENIED,
            f"Approval denied for step: {step_name}",
            payload={"step_name": step_name, "reason": reason, **kwargs},
            step_id=step_id,
            severity="warn",
            actor="user",
        )

    # --- Webhook events ---

    def webhook_callback_received(self, callback_id: str, action: str, **kwargs) -> None:
        """Emit webhook.callback_received event."""
        self.emit(
            EventType.WEBHOOK_CALLBACK_RECEIVED,
            f"Webhook callback received: {action}",
            payload={"callback_id": callback_id, "action": action, **kwargs},
            actor="user",
        )

    # --- Run suspension/resumption ---

    def run_suspended(self, reason: str, step_id: str | None = None, **kwargs) -> None:
        """Emit run.suspended event."""
        self.emit(
            EventType.RUN_SUSPENDED,
            f"Run suspended: {reason}",
            payload={"reason": reason, **kwargs},
            step_id=step_id,
            severity="warn",
        )

    def run_resumed(self, resume_source: str = "api", **kwargs) -> None:
        """Emit run.resumed event."""
        self.emit(
            EventType.RUN_RESUMED,
            f"Run resumed via {resume_source}",
            payload={"resume_source": resume_source, **kwargs},
            actor="user",
        )

    def step_skipped(self, step_id: str | None, step_name: str, condition: str, **kwargs) -> None:
        """Emit step.skipped event when a step's ``when`` guard evaluates false."""
        self.emit(
            EventType.STEP_SKIPPED,
            f"Step skipped: {step_name} (guard false)",
            payload={"step_name": step_name, "condition": condition, **kwargs},
            step_id=step_id,
        )

    def step_suspended(self, step_id: str | None, step_name: str, reason: str, **kwargs) -> None:
        """Emit step.suspended event (step-level pause, e.g. approval/wait)."""
        self.emit(
            EventType.STEP_SUSPENDED,
            f"Step suspended: {step_name} ({reason})",
            payload={"step_name": step_name, "reason": reason, **kwargs},
            step_id=step_id,
            severity="warn",
        )

    def step_resumed(
        self, step_id: str | None, step_name: str, resume_source: str = "api", **kwargs
    ) -> None:
        """Emit step.resumed event when a suspended step is advanced."""
        self.emit(
            EventType.STEP_RESUMED,
            f"Step resumed: {step_name} via {resume_source}",
            payload={"step_name": step_name, "resume_source": resume_source, **kwargs},
            step_id=step_id,
            actor="user",
        )

    # --- Artifact events ---

    def artifact_created(
        self,
        step_id: str | None,
        artifact_id: str,
        name: str,
        content_type: str = "",
        **kwargs,
    ) -> None:
        """Emit artifact.created event when an artifact is persisted."""
        self.emit(
            EventType.ARTIFACT_CREATED,
            f"Artifact created: {name}",
            payload={
                "artifact_id": artifact_id,
                "name": name,
                "content_type": content_type,
                **kwargs,
            },
            step_id=step_id,
        )

    # --- Critique events (post-execution) ---

    def critique_completed(
        self, step_id: str, verdict: str, confidence: float, reasoning: str, **kwargs
    ) -> None:
        """Emit a post-execution critique result as its own queryable event.

        Uses the dedicated CRITIQUE_COMPLETED type (not STEP_COMPLETED) so the
        critic verdict is independently auditable and does not double-signal
        step completion to the live overlay. A FAIL/ESCALATE verdict is raised
        as INFO here because the consequent step/run failure carries its own
        error-severity event.
        """
        self.emit(
            EventType.CRITIQUE_COMPLETED,
            f"Post-execution critique: {verdict} (confidence: {confidence:.2f})",
            payload={
                "verdict": verdict,
                "confidence": confidence,
                "reasoning": reasoning,
                **kwargs,
            },
            step_id=step_id,
            actor="llm",
            severity="warn" if verdict not in ("pass",) else "info",
            tags={"critique_verdict": verdict},
        )
