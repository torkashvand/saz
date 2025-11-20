"""Webhook and run resumption endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["webhooks"])

# Webhook endpoints are not yet implemented in RunService
# Uncomment and implement when ready:
#
# from saz.api.dependencies import RunServiceDep
# from saz.api.errors import NotFoundError
# from saz.api.schemas.webhook_schemas import (
#     ResumeRunRequest,
#     ResumeRunResponse,
#     WebhookEventPayload,
#     WebhookResponse,
# )
#
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
#
#
# @router.post("/runs/{run_id}/resume", response_model=ResumeRunResponse)
# async def resume_run(
#     run_id: str,
#     req: ResumeRunRequest,
#     service: RunServiceDep,
# ) -> ResumeRunResponse:
#     """Resume a suspended run."""
#     run = service.get(run_id)
#     if not run:
#         raise NotFoundError(f"Run not found: {run_id}")
#
#     if run.status != "suspended":
#         raise ValueError(f"Run {run_id} is not suspended (status: {run.status})")
#
#     service.resume_run(run_id, resume_data=req.resume_data, override_payload=req.override_payload)
#
#     return ResumeRunResponse(
#         run_id=run_id,
#         status="running",
#     )
