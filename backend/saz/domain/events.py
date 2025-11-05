"""Domain events for event-driven architecture."""
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any


@dataclass
class DomainEvent:
    """Base domain event."""
    event_type: str
    aggregate_id: str
    timestamp: datetime
    data: dict[str, Any]

    @classmethod
    def create(cls, event_type: str, aggregate_id: str, **data) -> "DomainEvent":
        """Factory method to create domain events."""
        return cls(
            event_type=event_type,
            aggregate_id=aggregate_id,
            timestamp=datetime.now(UTC),
            data=data
        )


# Run Events
@dataclass
class RunStarted(DomainEvent):
    """Event: Run execution started."""
    def __init__(self, run_id: str, flow_id: str):
        super().__init__(
            event_type="run.started",
            aggregate_id=run_id,
            timestamp=datetime.now(UTC),
            data={"flow_id": flow_id, "status": "running"}
        )


@dataclass
class RunCompleted(DomainEvent):
    """Event: Run execution completed successfully."""
    def __init__(self, run_id: str):
        super().__init__(
            event_type="run.completed",
            aggregate_id=run_id,
            timestamp=datetime.now(UTC),
            data={"status": "completed"}
        )


@dataclass
class RunFailed(DomainEvent):
    """Event: Run execution failed."""
    def __init__(self, run_id: str, error: dict):
        super().__init__(
            event_type="run.failed",
            aggregate_id=run_id,
            timestamp=datetime.now(UTC),
            data={"status": "failed", "error": error}
        )


@dataclass
class RunSuspended(DomainEvent):
    """Event: Run execution suspended."""
    def __init__(self, run_id: str, reason: str):
        super().__init__(
            event_type="run.suspended",
            aggregate_id=run_id,
            timestamp=datetime.now(UTC),
            data={"status": "suspended", "reason": reason}
        )


# Step Events
@dataclass
class StepStarted(DomainEvent):
    """Event: Step execution started."""
    def __init__(self, run_id: str, step_id: str, step_name: str):
        super().__init__(
            event_type="step.started",
            aggregate_id=run_id,
            timestamp=datetime.now(UTC),
            data={"step_id": step_id, "step_name": step_name, "status": "running"}
        )


@dataclass
class StepCompleted(DomainEvent):
    """Event: Step execution completed."""
    def __init__(self, run_id: str, step_id: str, duration_ms: int):
        super().__init__(
            event_type="step.completed",
            aggregate_id=run_id,
            timestamp=datetime.now(UTC),
            data={"step_id": step_id, "status": "completed", "duration_ms": duration_ms}
        )


@dataclass
class StepFailed(DomainEvent):
    """Event: Step execution failed."""
    def __init__(self, run_id: str, step_id: str, error: dict):
        super().__init__(
            event_type="step.failed",
            aggregate_id=run_id,
            timestamp=datetime.now(UTC),
            data={"step_id": step_id, "status": "failed", "error": error}
        )