"""Telemetry domain events for workflow execution traces."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

ToolExecutionStatus = Literal["success", "error"]
CritiqueVerdict = Literal["PASS", "FAIL", "ESCALATE", "REPLAN"]


@dataclass
class PIIStats:
    """PII transformation statistics."""

    tokenized_count: int = 0
    detokenized_paths: list[str] = field(default_factory=list)
    blocked_paths: list[str] = field(default_factory=list)


@dataclass
class PlanGeneratedEvent:
    """Emitted after execution plan is generated."""

    run_id: str
    total_steps: int
    steps: list[dict[str, Any]]  # [{id, intent, deps[]}]
    timestamp: datetime = field(default_factory=lambda: datetime.now())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "type": "trace.plan",
            "run_id": self.run_id,
            "total_steps": self.total_steps,
            "steps": self.steps,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class StepGroundedEvent:
    """Emitted after step is grounded (templates resolved)."""

    run_id: str
    step_id: str
    intent: str
    input_summary: str  # Safe, sanitized summary
    timestamp: datetime = field(default_factory=lambda: datetime.now())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "type": "trace.step.grounded",
            "run_id": self.run_id,
            "step_id": self.step_id,
            "intent": self.intent,
            "input_summary": self.input_summary,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class PolicyCheckEvent:
    """Emitted after policy check."""

    run_id: str
    step_id: str
    tool: str
    allowed: bool
    reason: str | None = None
    pii_stats: PIIStats | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        result = {
            "type": "trace.policy.check",
            "run_id": self.run_id,
            "step_id": self.step_id,
            "tool": self.tool,
            "allowed": self.allowed,
            "timestamp": self.timestamp.isoformat(),
        }

        if self.reason:
            result["reason"] = self.reason

        if self.pii_stats:
            result["pii_stats"] = {
                "tokenized_count": self.pii_stats.tokenized_count,
                "detokenized_paths": self.pii_stats.detokenized_paths,
                "blocked_paths": self.pii_stats.blocked_paths,
            }

        return result


@dataclass
class ToolStartEvent:
    """Emitted before tool execution."""

    run_id: str
    step_id: str
    tool: str
    attempt: int = 1
    timestamp: datetime = field(default_factory=lambda: datetime.now())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "type": "trace.tool.start",
            "run_id": self.run_id,
            "step_id": self.step_id,
            "tool": self.tool,
            "attempt": self.attempt,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ToolEndEvent:
    """Emitted after tool execution."""

    run_id: str
    step_id: str
    tool: str
    duration_ms: float
    status: ToolExecutionStatus
    error_type: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        result = {
            "type": "trace.tool.end",
            "run_id": self.run_id,
            "step_id": self.step_id,
            "tool": self.tool,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
        }

        if self.error_type:
            result["error_type"] = self.error_type

        return result


@dataclass
class RouteChosenEvent:
    """Emitted when a route/branch is chosen."""

    run_id: str
    step_id: str
    route: str
    signal_summary: str  # Safe, sanitized signal
    timestamp: datetime = field(default_factory=lambda: datetime.now())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "type": "trace.route.chosen",
            "run_id": self.run_id,
            "step_id": self.step_id,
            "route": self.route,
            "signal_summary": self.signal_summary,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class CritiqueEvent:
    """Emitted after step critique."""

    run_id: str
    step_id: str
    verdict: CritiqueVerdict
    confidence: float
    issues: list[str]  # Sanitized issue descriptions
    summary: str  # Safe summary
    timestamp: datetime = field(default_factory=lambda: datetime.now())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "type": "trace.critique",
            "run_id": self.run_id,
            "step_id": self.step_id,
            "verdict": self.verdict,
            "confidence": round(self.confidence, 2),
            "issues": self.issues[:5],  # Limit to 5 issues
            "summary": self.summary,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class UsageEvent:
    """Emitted after step execution with resource usage."""

    run_id: str
    step_id: str
    tokens: int
    cost_usd: float
    duration_ms: float
    timestamp: datetime = field(default_factory=lambda: datetime.now())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "type": "trace.usage",
            "run_id": self.run_id,
            "step_id": self.step_id,
            "tokens": self.tokens,
            "cost_usd": round(self.cost_usd, 4),
            "duration_ms": round(self.duration_ms, 2),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RunProgressEvent:
    """Emitted periodically to show run progress."""

    run_id: str
    completed: int
    total: int
    percent: float
    timestamp: datetime = field(default_factory=lambda: datetime.now())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "type": "trace.progress",
            "run_id": self.run_id,
            "completed": self.completed,
            "total": self.total,
            "percent": round(self.percent, 1),
            "timestamp": self.timestamp.isoformat(),
        }
