"""Webhook and run resumption endpoints."""

import logging

from fastapi import APIRouter

from saz.api.dependencies import RunServiceDep, UnitOfWorkDep
from saz.api.errors import NotFoundError, ValidationError
from saz.api.schemas.webhook_schemas import (
    ResumeRunRequest,
    ResumeRunResponse,
    WebhookCallbackRequest,
    WebhookCallbackResponse,
)
from saz.audit.event_emitter import EventEmitter
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


@router.post(
    "/webhooks/callback/{callback_id}",
    response_model=WebhookCallbackResponse,
)
async def handle_webhook_callback(
    callback_id: str,
    req: WebhookCallbackRequest,
    uow: UnitOfWorkDep,
) -> WebhookCallbackResponse:
    """
    Handle inbound webhook callback for suspended runs.

    When a run suspends for human approval or webhook wait, it generates
    a unique callback_id. External systems can POST to this endpoint
    with that callback_id to approve/reject and resume the run.

    Security:
    - callback_id is a non-guessable UUID hex (32 chars)
    - Only suspended runs can be resumed
    - Duplicate callbacks are handled idempotently

    Args:
        callback_id: Unique callback identifier generated at suspension
        req: Callback payload with action (approve/reject) and optional data

    Returns:
        Callback response with status and run_id

    Raises:
        NotFoundError: If no suspended run matches the callback_id
        ValidationError: If run is not in a resumable state
    """
    logger.info(f"Webhook callback received: {callback_id}, action: {req.action}")

    # Find the suspended run by callback_id
    assert uow.runs is not None
    run = uow.runs.find_by_callback_id(callback_id)

    if not run:
        raise NotFoundError(f"No suspended run found for callback_id: {callback_id}")

    # Idempotency: if run is already not suspended, return success
    if run.status != "suspended":
        return WebhookCallbackResponse(
            status="already_processed",
            run_id=run.id,
            message=f"Run already in state: {run.status}",
        )

    # Validate action
    if req.action not in ("approve", "reject"):
        raise ValidationError(f"Invalid action '{req.action}'. Must be 'approve' or 'reject'.")

    # Emit webhook callback received event
    emitter = EventEmitter(
        uow=uow,
        run_id=run.id,
        planner_mode=run.planner_mode or "deterministic",
        pii_policy="redact",
    )
    emitter.webhook_callback_received(
        callback_id=callback_id,
        action=req.action,
    )

    if req.action == "reject":
        # Rejection: fail the run
        reason = req.reason or "Rejected via webhook callback"
        emitter.approval_denied(
            step_id=run.error.get("step_id", "") if run.error else "",
            step_name=run.error.get("step_id", "") if run.error else "",
            reason=reason,
        )

        uow.runs.mark_failed(
            run.id,
            {
                "message": f"Rejected via webhook: {reason}",
                "type": "WebhookRejection",
                "callback_id": callback_id,
            },
        )
        emitter.run_failed(error=reason, error_type="WebhookRejection")
        await emitter.commit_and_broadcast()

        return WebhookCallbackResponse(
            status="rejected",
            run_id=run.id,
            message=f"Run rejected: {reason}",
        )

    # Approval: resume the run
    resume_data = {
        "approved": True,
        "callback_id": callback_id,
        "action": req.action,
        **(req.data or {}),
    }

    # Find and complete the suspended step
    assert uow.steps is not None
    assert uow.run_reads is not None
    run_detail = uow.run_reads.detail(run.id)
    if run_detail:
        for step_dto in run_detail.steps:
            if step_dto.status == "suspended":
                step_entity = uow.steps.get(step_dto.id)
                if step_entity:
                    step_entity.output = resume_data
                    uow.steps.mark_completed(step_dto.id)
                break

    # Emit approval granted
    step_id = run.error.get("step_id", "") if run.error else ""
    emitter.approval_granted(step_id=step_id, step_name=step_id)
    emitter.run_resumed(resume_source="webhook_callback")

    # Mark run as queued, preserving callback_id for idempotent duplicate detection.
    # Merge resolved marker into the existing error dict so the original suspension
    # context (step_id, type, reasoning) remains available for audit/debugging.
    resolved_error = {**(run.error or {}), "callback_id": callback_id, "resolved": True}
    run.status = "queued"
    run.error = resolved_error
    await emitter.commit_and_broadcast()

    # Schedule run for re-execution
    scheduler = get_scheduler()
    scheduler.schedule(run.id)

    return WebhookCallbackResponse(
        status="resumed",
        run_id=run.id,
        message="Run approved and resumed via webhook callback",
    )
