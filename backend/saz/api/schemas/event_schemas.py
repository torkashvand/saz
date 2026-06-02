"""Pydantic schemas for event API responses."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from saz.domain.literals import Actor, PlannerMode, RunStatus, Severity


class EventResponse(BaseModel):
    """API response for a single event."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    timestamp: datetime
    schema_version: int
    seq: int | None = None

    run_id: str
    step_id: str | None = None
    correlation_id: str | None = None

    planner_mode: PlannerMode
    severity: Severity
    actor: Actor
    actor_user_id: str | None = None

    summary: str
    payload: dict[str, Any]
    tags: dict[str, str]


class EventListResponse(BaseModel):
    """Paginated list of events."""

    events: list[EventResponse]
    total: int
    cursor: str | None = None  # Next page cursor (ISO timestamp)
    has_more: bool


class RunSummaryResponse(BaseModel):
    """Run summary with aggregated metrics from events."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    flow_id: str
    status: RunStatus
    planner_mode: PlannerMode

    created_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None

    # Aggregated from events
    total_events: int = 0
    event_counts: dict[str, int] = Field(default_factory=dict)  # By event_type
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    error_count: int = 0
