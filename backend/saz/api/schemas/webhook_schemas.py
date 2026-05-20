"""Pydantic schemas for webhook-related endpoints."""

from typing import Any, Literal

from pydantic import BaseModel

WebhookCallbackAction = Literal["approve", "reject"]
WebhookCallbackStatus = Literal["resumed", "rejected", "already_processed"]


class WebhookEventPayload(BaseModel):
    """Generic webhook event payload."""

    event_name: str
    data: dict[str, Any]
    timestamp: str | None = None
    metadata: dict[str, Any] | None = None


class WebhookResponse(BaseModel):
    """Response after receiving webhook."""

    status: Literal["received"] = "received"
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


class WebhookCallbackRequest(BaseModel):
    """Inbound webhook callback payload for resuming suspended runs."""

    action: WebhookCallbackAction = "approve"
    data: dict[str, Any] | None = None
    reason: str | None = None


class WebhookCallbackResponse(BaseModel):
    """Response after processing a webhook callback."""

    status: WebhookCallbackStatus
    run_id: str
    message: str
