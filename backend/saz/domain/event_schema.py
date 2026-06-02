"""Unified event schema for Saz audit and telemetry."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from saz.domain.literals import Actor, PlannerMode, Severity


def now_utc():
    return datetime.now(UTC)


class EventType(str, Enum):
    """Stable, hierarchical event taxonomy for Saz."""

    # Run lifecycle
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    RUN_SUSPENDED = "run.suspended"
    RUN_RESUMED = "run.resumed"

    # Step lifecycle
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    STEP_SKIPPED = "step.skipped"
    STEP_SUSPENDED = "step.suspended"
    STEP_RESUMED = "step.resumed"

    # Tool execution
    TOOL_STARTED = "tool.started"
    TOOL_SUCCEEDED = "tool.succeeded"
    TOOL_FAILED = "tool.failed"

    # Planner (agentic mode)
    PLAN_GENERATED = "plan.generated"
    PLAN_UPDATED = "plan.updated"
    BRANCH_CHOSEN = "branch.chosen"

    # Verifier (pre-execution)
    VERIFIER_APPROVED = "verifier.approved"
    VERIFIER_REJECTED = "verifier.rejected"
    VERIFIER_REPLAN_REQUESTED = "verifier.replan_requested"
    VERIFIER_ESCALATED = "verifier.escalated"

    # Replanning
    REPLAN_ATTEMPTED = "replan.attempted"
    REPLAN_SUCCEEDED = "replan.succeeded"
    REPLAN_EXHAUSTED = "replan.exhausted"

    # Critic (post-execution)
    CRITIQUE_COMPLETED = "critique.completed"

    # Webhook
    WEBHOOK_CALLBACK_RECEIVED = "webhook.callback_received"

    # Policy & safety
    POLICY_PII_REDACTED = "policy.pii.redacted"
    POLICY_BUDGET_UPDATED = "policy.budget.updated"
    POLICY_BUDGET_EXHAUSTED = "policy.budget.exhausted"
    POLICY_RATE_LIMITED = "policy.rate_limited"
    POLICY_BLOCKED = "policy.blocked"

    # Usage & progress
    USAGE_RECORDED = "usage.recorded"
    PROGRESS_UPDATED = "progress.updated"

    # Human interaction
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"
    ACTION_ABORTED = "action.aborted"

    # Artifacts
    ARTIFACT_CREATED = "artifact.created"

    # System
    SYSTEM_ERROR = "system.error"
    SYSTEM_WARNING = "system.warning"


@dataclass
class Event:
    """
    Base event structure for all Saz audit events.

    All events in the system follow this schema, providing a consistent
    structure for audit logging, telemetry, and observability.
    """

    # Identity
    id: str = field(default_factory=lambda: f"evt_{uuid4().hex[:12]}")
    event_type: EventType = field(default=EventType.SYSTEM_ERROR)
    timestamp: datetime = field(default_factory=now_utc)
    schema_version: int = 1
    # Monotonic per-run sequence assigned at persist time. None until persisted;
    # consumers sort by (timestamp, seq) for a deterministic, gap-aware order.
    seq: int | None = None

    # Context
    run_id: str = ""
    step_id: str | None = None
    correlation_id: str | None = None  # For tracing causal chains

    # Metadata
    planner_mode: PlannerMode = PlannerMode.DETERMINISTIC
    severity: Severity = Severity.INFO
    actor: Actor = Actor.SYSTEM
    # Set only when actor == "user". NULL for system/LLM events by design.
    actor_user_id: str | None = None

    # Content
    summary: str = ""  # Human-readable one-liner
    payload: dict[str, Any] = field(default_factory=dict)  # Type-specific data

    # Observability
    tags: dict[str, str] = field(default_factory=dict)  # For grouping/filtering

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "schema_version": self.schema_version,
            "seq": self.seq,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "correlation_id": self.correlation_id,
            "planner_mode": self.planner_mode,
            "severity": self.severity,
            "actor": self.actor,
            "actor_user_id": self.actor_user_id,
            "summary": self.summary,
            "payload": self.payload,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        """Create event from dictionary."""
        # Parse timestamp if it's a string
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        # Parse event_type if it's a string
        event_type = data.get("event_type")
        if isinstance(event_type, str):
            event_type = EventType(event_type)
        elif not isinstance(event_type, EventType):
            raise ValueError(f"Invalid event_type: {event_type}")

        return cls(
            id=data.get("id", f"evt_{uuid4().hex[:12]}"),
            event_type=event_type,
            timestamp=timestamp or datetime.now(UTC),
            schema_version=data.get("schema_version", 1),
            seq=data.get("seq"),
            run_id=data.get("run_id", ""),
            step_id=data.get("step_id"),
            correlation_id=data.get("correlation_id"),
            planner_mode=PlannerMode(data.get("planner_mode", "deterministic")),
            severity=Severity(data.get("severity", "info")),
            actor=Actor(data.get("actor", "system")),
            actor_user_id=data.get("actor_user_id"),
            summary=data.get("summary", ""),
            payload=data.get("payload", {}),
            tags=data.get("tags", {}),
        )
