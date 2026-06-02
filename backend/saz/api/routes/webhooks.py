"""Webhook and run resumption endpoints."""

import logging

from fastapi import APIRouter

from saz.api.dependencies import CurrentUserDep, RunServiceDep, UnitOfWorkDep
from saz.api.errors import NotFoundError, ValidationError
from saz.api.schemas.webhook_schemas import (
    ResumeRunRequest,
    ResumeRunResponse,
    WebhookCallbackRequest,
    WebhookCallbackResponse,
)
from saz.audit.event_emitter import EventEmitter
from saz.domain.event_schema import EventType
from saz.engine.scheduler import get_scheduler

router = APIRouter(prefix="/api/v1", tags=["webhooks"])
logger = logging.getLogger(__name__)


@router.post("/runs/{run_id}/resume", response_model=ResumeRunResponse)
async def resume_run(
    run_id: str,
    req: ResumeRunRequest,
    service: RunServiceDep,
    user: CurrentUserDep,
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

    # Pre-buffer the user-attributed event into the same UoW the service
    # will commit, so attribution does not add a second DB transaction.
    # We reuse the planner_mode from the read-side ``run`` DTO above
    # rather than issuing another SELECT — an extra round-trip widens a
    # pre-existing race window in tests that simulate post-resume state
    # immediately after the response (the executor thread had more
    # wall-clock to run before the test's next line). The DTO does not
    # carry planner_mode today; default to "deterministic" so this stays
    # query-free.
    emitter = EventEmitter(
        uow=service.uow,
        run_id=run_id,
        planner_mode="deterministic",
        pii_policy="redact",
        actor_user_id=user.id,
    )
    emitter.emit(
        EventType.RUN_RESUMED,
        f"Run resumed by {user.username}",
        payload={"resume_source": "api", "username": user.username},
        actor="user",
    )

    # Emit a step-level resume event for the suspended step so the timeline
    # records which step was advanced (mirrors the webhook-callback path).
    suspended_step = next((s for s in run.steps if s.status == "suspended"), None)
    if suspended_step is not None:
        emitter.step_resumed(
            step_id=suspended_step.id,
            step_name=suspended_step.name,
            resume_source="api",
        )

    # Resume the run (marks as queued, stores resume data, commits — also
    # flushes the buffered audit event in the same transaction).
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

    # Locate the suspended step ONCE so both approve and reject paths can
    # emit events with the correct DB-level step.id (events.step_id has a
    # foreign-key constraint to steps.id on PostgreSQL — passing the
    # step *name* trips the FK and 500s the request).
    assert uow.steps is not None
    suspended_step = uow.steps.get_first_suspended_for_run(run.id)
    suspended_step_db_id: str | None = suspended_step.id if suspended_step else None
    suspended_step_name: str = (suspended_step.name if suspended_step else None) or (
        run.error.get("step_id", "") if run.error else ""
    )

    if req.action == "reject":
        # Rejection: fail the suspended step AND the run.
        # A failed run must never own a "suspended" step row — that confuses
        # the timeline UI, retry/resume logic, and any audit consumer that
        # expects terminal step state on a terminal run. The rejection reason
        # also belongs on Step.error so operators see WHY the gate failed
        # without digging through run.error.
        reason = req.reason or "Rejected via webhook callback"
        emitter.approval_denied(
            step_id=suspended_step_db_id,
            step_name=suspended_step_name,
            reason=reason,
        )

        if suspended_step_db_id is not None:
            uow.steps.mark_failed(
                suspended_step_db_id,
                {
                    "type": "WebhookRejection",
                    "message": f"Rejected via webhook: {reason}",
                    "reason": reason,
                    "callback_id": callback_id,
                },
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

    # Complete the suspended step with the resume payload so downstream
    # steps can template-access the callback data via $step('id').field.
    if suspended_step_db_id is not None:
        step_entity = uow.steps.get(suspended_step_db_id)
        if step_entity:
            step_entity.output = resume_data
            uow.steps.mark_completed(suspended_step_db_id)

    # Emit approval granted with the DB-level step id (FK-safe) and the
    # human-readable step name for the audit trail.
    emitter.approval_granted(
        step_id=suspended_step_db_id,
        step_name=suspended_step_name,
    )
    if suspended_step_db_id is not None:
        emitter.step_resumed(
            step_id=suspended_step_db_id,
            step_name=suspended_step_name,
            resume_source="webhook_callback",
        )
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
