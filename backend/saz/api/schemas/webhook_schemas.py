"""Pydantic schemas for webhook-related endpoints."""

from typing import Any

from pydantic import BaseModel


class WebhookEventPayload(BaseModel):
    """Generic webhook event payload."""

    event_name: str
    data: dict[str, Any]
    timestamp: str | None = None
    metadata: dict[str, Any] | None = None


class WebhookResponse(BaseModel):
    """Response after receiving webhook."""

    status: str = "received"
    message: str
    affected_runs: int = 0


class ResumeRunRequest(BaseModel):
    """Request to resume a suspended run."""

    resume_data: dict[str, Any] | None = None
    override_payload: dict[str, Any] | None = None


class ResumeRunResponse(BaseModel):
    """Response after resuming a run."""

    run_id: str
    status: str
