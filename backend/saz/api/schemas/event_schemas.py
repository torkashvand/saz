"""Pydantic schemas for event API responses."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EventResponse(BaseModel):
    """API response for a single event."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    timestamp: datetime
    schema_version: int

    run_id: str
    step_id: str | None = None
    correlation_id: str | None = None

    planner_mode: Literal["deterministic", "agentic"]
    severity: Literal["info", "warn", "error"]
    actor: Literal["system", "user", "llm"]

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
    status: str
    planner_mode: str

    created_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None

    # Aggregated from events
    total_events: int = 0
    event_counts: dict[str, int] = Field(default_factory=dict)  # By event_type
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    error_count: int = 0
