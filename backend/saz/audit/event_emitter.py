"""Helper functions for emitting audit events from the engine."""

from datetime import UTC, datetime
from typing import Any, Literal, cast

from saz.audit.event_bus import event_bus
from saz.audit.sanitizer import AuditSanitizer
from saz.db.unit_of_work import UnitOfWork
from saz.domain.event_schema import Event, EventType


class EventEmitter:
    """
    Helper class for emitting audit events from workflow execution.

    Simplifies event creation and ensures consistent patterns.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        run_id: str,
        planner_mode: str,
        pii_policy: str = "redact",
    ):
        self.uow = uow
        self.run_id = run_id
        self.planner_mode = planner_mode
        self.sanitizer = AuditSanitizer()
        self.pii_policy = pii_policy

    def emit(
        self,
        event_type: EventType,
        summary: str,
        payload: dict[str, Any] | None = None,
        step_id: str | None = None,
        correlation_id: str | None = None,
        severity: str = "info",
        actor: str = "system",
        tags: dict[str, str] | None = None,
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
        """
        # Sanitize payload
        sanitized_payload = self.sanitizer.redact_payload(payload or {}, self.pii_policy)

        event = Event(
            event_type=event_type,
            run_id=self.run_id,
            step_id=step_id,
            correlation_id=correlation_id,
            planner_mode=cast(Literal["deterministic", "agentic"], self.planner_mode),
            severity=cast(Literal["info", "warn", "error"], severity),
            actor=cast(Literal["system", "user", "llm"], actor),
            summary=summary,
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
