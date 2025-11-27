"""Webhook and run resumption endpoints."""

import logging

from fastapi import APIRouter

from saz.api.dependencies import RunServiceDep
from saz.api.errors import NotFoundError, ValidationError
from saz.api.schemas.webhook_schemas import (
    ResumeRunRequest,
    ResumeRunResponse,
)
from saz.engine.scheduler import get_scheduler

router = APIRouter(prefix="/api/v1", tags=["webhooks"])
logger = logging.getLogger(__name__)


@router.post("/runs/{run_id}/resume", response_model=ResumeRunResponse)
async def resume_run(
    run_id: str,
    req: ResumeRunRequest,
    service: RunServiceDep,
) -> ResumeRunResponse:
    """
    Resume a suspended run.

    This endpoint allows resuming runs that have been suspended due to:
    - Human approval gates (human.approval step type)
    - Escalation from critic agent (ESCALATE verdict)
    - Webhook wait conditions (webhook.wait step type)

    The resume_data is stored in the suspended step's output and can be
    accessed by subsequent steps via template expressions.

    Args:
        run_id: Run identifier
        req: Resume request with optional data and payload overrides
        service: Run service dependency

    Returns:
        Resume response with run status

    Raises:
        NotFoundError: If run not found
        ValidationError: If run is not suspended
    """
    logger.info(f"Resuming run {run_id} with data: {req.resume_data}")

    # Get run detail
    run = service.get(run_id)
    if not run:
        raise NotFoundError(f"Run not found: {run_id}")

    if run.status != "suspended":
        raise ValidationError(f"Run {run_id} is not suspended (status: {run.status})")

    # Resume the run (marks as queued, stores resume data)
    service.resume_run(
        run_id,
        resume_data=req.resume_data,
        override_payload=req.override_payload,
    )

    # Re-schedule run for execution
    scheduler = get_scheduler()
    scheduled = scheduler.schedule(run_id)

    if not scheduled:
        logger.warning(f"Run {run_id} could not be scheduled (already running?)")

    return ResumeRunResponse(
        run_id=run_id,
        status="queued",
    )


# Webhook event handling - to be implemented when needed
# @router.post("/webhooks/{event_name}", response_model=WebhookResponse)
# async def handle_webhook(
#     event_name: str,
#     payload: WebhookEventPayload,
#     service: RunServiceDep,
# ) -> WebhookResponse:
#     """Handle incoming webhook events."""
#     affected_runs = service.handle_webhook_event(event_name, payload.data)
#
#     return WebhookResponse(
#         status="received",
#         message=f"Webhook '{event_name}' processed",
#         affected_runs=affected_runs,
#     )
