"""Run management and execution endpoints."""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query

from saz.api.dependencies import CurrentUserDep, RunServiceDep
from saz.api.errors import NotFoundError
from saz.api.schemas.event_schemas import EventListResponse, EventResponse
from saz.api.schemas.run_schemas import (
    ComplianceReportResponse,
    CreateRunRequest,
    CreateRunResponse,
    ErrorSummarySchema,
    ExecutionGraphResponse,
    PlannedStepSchema,
    RetryRunRequest,
    RetryRunResponse,
    RunDetailResponse,
    RunListItem,
    RunListResponse,
    RunMetadataSchema,
    RunStepsResponse,
    RunSummary,
    StepSummary,
    TriggeredBySchema,
)
from saz.audit.event_emitter import EventEmitter
from saz.domain.error_enrichment import ErrorEnrichmentService
from saz.domain.event_schema import EventType
from saz.engine.scheduler import get_scheduler
from saz.settings import settings

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])
logger = logging.getLogger(__name__)


def sanitize_error(error: dict | None, include_sensitive: bool) -> dict | None:
    """
    Sanitize an error dict for outbound API responses.

    The default strips stack traces / tracebacks (sensitive in production)
    but keeps the operator-facing fields the UI needs to render suspended
    and failed runs — most notably the ``callback_id`` that drives the
    webhook + approval panels, and ``timeout_at`` for the suspension
    countdown.

    Args:
        error: Error dictionary from Step.error or Run.error
        include_sensitive: Whether to include stack traces (debug only)

    Returns:
        Sanitized error dict or None
    """
    if not error:
        return None

    if include_sensitive:
        # Return full error including stack traces
        return error

    # Whitelist of operator-safe fields. Anything not in this list is
    # dropped — so `traceback` / `stack_trace` / arbitrary debug payloads
    # never leak. New audit-relevant fields must be added here explicitly.
    SAFE_FIELDS = (
        "type",
        "message",
        "status_code",
        # Suspension + callback wiring — read by HumanApprovalPanel and
        # WebhookCallbackPanel on the frontend.
        "callback_id",
        "step_id",
        "reasoning",
        "suspended_at",
        "timeout_at",
        "timeout_minutes",
        # Suspension timeout audit (set by the SuspensionSweeper) — needed
        # so the UI can distinguish "timed out" from "still suspended" and
        # so late callbacks return already_processed.
        "original_type",
        "timed_out_at",
        # Webhook callback resolution marker
        "resolved",
    )
    sanitized: dict[str, Any] = {k: error[k] for k in SAFE_FIELDS if k in error}
    return sanitized


@router.get("", response_model=RunListResponse)
async def list_runs(
    service: RunServiceDep,
    _user: CurrentUserDep,
    flow_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> RunListResponse:
    """List runs with optional filtering."""
    # Use read repository which returns DTOs with flow_name included
    assert service.uow.run_reads is not None
    run_dtos, total = service.uow.run_reads.list(
        flow_id=flow_id, status=status, limit=limit, offset=offset
    )

    # For each DTO, get the Run model to access flow relationship
    assert service.uow.runs is not None
    runs_with_flow = []
    for dto in run_dtos:
        run = service.uow.runs.get(dto.id)
        if run:
            runs_with_flow.append(run)

    return RunListResponse(
        items=[
            RunListItem(
                id=r.id,
                flow_id=r.flow_id,
                flow_name=r.flow.name if r.flow else "Unknown",
                status=r.status,
                created_at=r.created_at,
                completed_at=r.completed_at,
                total_cost_usd=r.total_cost_usd or 0.0,
                total_tokens=r.total_tokens or 0,
                error=sanitize_error(r.error, include_sensitive=False),
            )
            for r in runs_with_flow
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=CreateRunResponse)
async def create_run(
    req: CreateRunRequest,
    service: RunServiceDep,
    user: CurrentUserDep,
) -> CreateRunResponse:
    """Create and start a new run."""
    run_id = service.create(
        flow_id=req.flow_id,
        payload=req.payload or {},
        created_by_user_id=user.id,
    )

    assert service.uow.runs is not None
    run = service.uow.runs.get(run_id)
    if not run:
        raise NotFoundError(f"Run not found after creation: {run_id}")

    run.triggered_by = {
        "type": "user",
        "user_id": user.id,
        "user_name": user.display_name or user.username,
        "trigger_source": "manual",
    }
    service.uow.commit()

    # Schedule the run for execution
    scheduler = get_scheduler()
    scheduled = scheduler.schedule(run_id)
    if not scheduled:
        # Run is already scheduled/running, which shouldn't happen for new runs
        # but we'll log it and continue
        logger.warning(f"Run {run_id} could not be scheduled (already running?)")

    return CreateRunResponse(
        id=run.id,
        flow_id=run.flow_id,
        status=run.status,
    )


@router.get("/{run_id}/summary", response_model=RunSummary)
async def get_run_summary(
    run_id: str,
    service: RunServiceDep,
    _user: CurrentUserDep,
) -> RunSummary:
    """Get run summary with basic information."""
    # Access Run model directly to get all fields
    assert service.uow.runs is not None
    run = service.uow.runs.get(run_id)
    if not run:
        raise NotFoundError(f"Run not found: {run_id}")

    return RunSummary(
        id=run.id,
        flow_id=run.flow_id,
        flow_name=run.flow.name if run.flow else "Unknown",
        status=run.status,
        created_at=run.created_at,
        completed_at=run.completed_at,
        total_cost_usd=run.total_cost_usd or 0.0,
        total_tokens=run.total_tokens or 0,
        step_count=len(run.steps) if run.steps else 0,
        error=sanitize_error(run.error, include_sensitive=False),
    )


@router.get("/{run_id}/events", response_model=EventListResponse)
async def get_run_events(
    run_id: str,
    service: RunServiceDep,
    _user: CurrentUserDep,
    event_type: list[str] | None = Query(None),
    severity: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = Query(None),
) -> EventListResponse:
    """Get events for a specific run with filtering and pagination."""
    # Verify run exists
    assert service.uow.runs is not None
    run = service.uow.runs.get(run_id)
    if not run:
        raise NotFoundError(f"Run not found: {run_id}")

    # Parse datetime filters if provided
    since_dt = datetime.fromisoformat(since) if since else None
    until_dt = datetime.fromisoformat(until) if until else None

    # Access event_queries through UoW
    assert service.uow.event_queries is not None
    events, next_cursor = service.uow.event_queries.get_by_run(
        run_id=run_id,
        event_types=event_type,
        severity=severity,
        since=since_dt,
        until=until_dt,
        limit=limit,
        cursor=cursor,
    )

    return EventListResponse(
        events=[EventResponse.model_validate(e) for e in events],
        total=len(events),
        cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.get("/{run_id}", response_model=RunDetailResponse)
async def get_run_detail(
    run_id: str,
    service: RunServiceDep,
    _user: CurrentUserDep,
    include_sensitive: bool = Query(False, description="Include stack traces (for debugging only)"),
) -> RunDetailResponse:
    """Get run detail with steps and enhanced UX fields.

    By default, stack traces and sensitive error details are NOT included.

    The include_sensitive parameter only works if ALLOW_SENSITIVE_DATA=true in environment.
    This prevents accidental exposure in production even if the parameter is set.
    """
    # Override include_sensitive based on environment variable
    # Even if client requests sensitive data, deny if env var is False
    include_sensitive = include_sensitive and settings.ALLOW_SENSITIVE_DATA

    if include_sensitive:
        logger.warning(
            "Sensitive data requested and allowed by environment",
            extra={"run_id": run_id, "endpoint": f"/api/v1/runs/{run_id}"},
        )
    # Get run model directly to access all fields
    assert service.uow.runs is not None
    run = service.uow.runs.get(run_id)
    if not run:
        raise NotFoundError(f"Run not found: {run_id}")

    # Calculate duration if completed
    duration_ms = None
    if run.completed_at and run.created_at:
        duration_ms = int((run.completed_at - run.created_at).total_seconds() * 1000)

    # Import enrichment service
    from saz.api.schemas.run_schemas import (
        StepSummary,
    )

    # Build error summary if run failed
    error_summary_obj = None
    if run.status in ("failed", "error"):
        # After retry a run may have multiple failed step attempts.
        # We must use the latest attempt per step name so the error summary
        # reflects the most recent failure, not a stale historical one.
        latest_by_name: dict[str, Any] = {}
        for s in run.steps or []:
            existing = latest_by_name.get(s.name)
            if existing is None or s.attempt > existing.attempt:
                latest_by_name[s.name] = s
        latest_steps = sorted(latest_by_name.values(), key=lambda s: s.number)
        failed_step = next((s for s in latest_steps if s.status == "failed"), None)
        error_summary = ErrorEnrichmentService.build_error_summary(run, failed_step)
        if error_summary:
            error_summary_obj = ErrorSummarySchema(**error_summary.to_dict())

    # Calculate metadata
    metadata = ErrorEnrichmentService.calculate_run_metadata(run)
    metadata_obj = RunMetadataSchema(**metadata)

    # Get flow definition for step descriptions
    assert service.uow.flows is not None
    flow = service.uow.flows.get(run.flow_id)
    flow_definition = flow.definition if flow else None

    # Convert steps to StepSummary with enrichment
    enriched_steps = []
    for s in run.steps or []:
        # Get step description from flow definition
        description = ErrorEnrichmentService.get_step_description(s, flow_definition)

        # Get failure reason if step failed
        failure_reason, error_category = ErrorEnrichmentService.enrich_step_with_failure_reason(s)

        enriched_steps.append(
            StepSummary(
                id=s.id,
                number=s.number,
                name=s.name,
                attempt=s.attempt,
                step_type=s.step_type,
                status=s.status,
                start_ts=s.start_ts,
                end_ts=s.end_ts,
                duration_ms=s.duration_ms,
                retry_count=s.retry_count,
                tokens=s.tokens,
                cost_usd=s.cost_usd,
                input=s.input,
                output=s.output,
                error=sanitize_error(s.error, include_sensitive),  # Sanitize error
                description=description,
                failure_reason=failure_reason,
                error_category=error_category,
            )
        )

    # Build triggered_by object
    triggered_by_obj = None
    if run.triggered_by:
        triggered_by_obj = TriggeredBySchema(**run.triggered_by)

    # Extract planned steps from flow definition
    planned_steps_list: list[PlannedStepSchema] = []
    if flow_definition:
        workflow_steps = flow_definition.get("workflow", {}).get("steps", [])
        for idx, step_def in enumerate(workflow_steps):
            step_type = step_def.get("type", "unknown")
            step_id = step_def.get("id", f"step_{idx}")

            # AI steps use 'instruction', other steps use 'description'
            if step_type and step_type.startswith("ai."):
                step_name = step_def.get("instruction", step_id)
            else:
                step_name = step_def.get("description", step_id)

            planned_steps_list.append(
                PlannedStepSchema(
                    index=idx,
                    id=step_id,
                    name=step_name,
                    step_type=step_type,
                )
            )

    return RunDetailResponse(
        id=run.id,
        flow_id=run.flow_id,
        flow_name=run.flow.name,
        status=run.status,
        planner_mode=run.planner_mode,
        payload=run.payload or {},
        error=sanitize_error(run.error, include_sensitive),  # Sanitize run-level error
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_ms=duration_ms or run.duration_ms,
        total_tokens=run.total_tokens or 0,
        total_cost_usd=run.total_cost_usd or 0.0,
        policy_violations=run.policy_violations,
        steps=enriched_steps,
        error_summary=error_summary_obj,
        run_metadata=metadata_obj,
        triggered_by=triggered_by_obj,
        planned_steps=planned_steps_list,
    )


@router.get("/{run_id}/steps", response_model=RunStepsResponse)
async def get_run_steps(
    run_id: str,
    service: RunServiceDep,
    _user: CurrentUserDep,
) -> RunStepsResponse:
    """Get execution steps for a run."""
    # Access Run model directly
    assert service.uow.runs is not None
    run = service.uow.runs.get(run_id)
    if not run:
        raise NotFoundError(f"Run not found: {run_id}")

    # Convert steps to StepSummary

    return RunStepsResponse(
        run_id=run.id,
        status=run.status,
        steps=[
            StepSummary(
                id=s.id,
                number=s.number,
                name=s.name,
                attempt=s.attempt,
                step_type=s.step_type,
                status=s.status,
                start_ts=s.start_ts,
                end_ts=s.end_ts,
                duration_ms=s.duration_ms,
                retry_count=s.retry_count,
                tokens=s.tokens,
                cost_usd=s.cost_usd,
                input=s.input,
                output=s.output,
                error=sanitize_error(s.error, include_sensitive=False),
            )
            for s in (run.steps or [])
        ],
    )


@router.get("/{run_id}/graph", response_model=ExecutionGraphResponse)
async def get_run_graph(
    run_id: str,
    service: RunServiceDep,
    _user: CurrentUserDep,
) -> ExecutionGraphResponse:
    """Get execution graph for a run (nodes and edges)."""
    # Access Run model directly
    assert service.uow.runs is not None
    run = service.uow.runs.get(run_id)
    if not run:
        raise NotFoundError(f"Run not found: {run_id}")

    # Get flow to build graph structure
    assert service.uow.flows is not None
    flow = service.uow.flows.get(run.flow_id)
    if not flow:
        return ExecutionGraphResponse(run_id=run.id, nodes=[], edges=[])

    # Build graph from workflow steps
    workflow_steps = flow.definition.get("workflow", {}).get("steps", [])
    nodes = []
    edges = []

    for idx, step in enumerate(workflow_steps):
        step_id = step.get("id", f"step_{idx}")
        step_type = step.get("type", "unknown")
        step_instruction = step.get("instruction", step.get("description", step_id))

        nodes.append(
            {
                "id": step_id,
                "label": step_instruction[:50] + "..."
                if len(step_instruction) > 50
                else step_instruction,
                "type": step_type,
            }
        )

        if idx > 0:
            prev_step_id = workflow_steps[idx - 1].get("id", f"step_{idx - 1}")
            edges.append({"from": prev_step_id, "to": step_id})

    return ExecutionGraphResponse(
        run_id=run.id,
        nodes=nodes,
        edges=edges,
    )


@router.post("/{run_id}/retry", response_model=RetryRunResponse)
async def retry_run_endpoint(
    run_id: str,
    service: RunServiceDep,
    user: CurrentUserDep,
    req: RetryRunRequest | None = None,
) -> RetryRunResponse:
    """Retry a failed run from the point of failure (same-run semantics).

    The same run is reused — no new run is created. Historical step attempts
    are preserved. The run is reset to 'queued' and rescheduled.
    """
    assert service.uow.runs is not None
    run = service.uow.runs.get(run_id)
    if not run:
        raise NotFoundError(f"Run not found: {run_id}")

    if run.status not in ["failed", "error"]:
        raise ValueError(f"Run {run_id} cannot be retried (status: {run.status})")

    # Pre-buffer the user-attributed event so retry+attribution share one
    # UoW commit. See webhooks.resume_run for why a second commit here
    # would widen pre-existing test races around scheduler timing.
    emitter = EventEmitter(
        uow=service.uow,
        run_id=run.id,
        planner_mode=run.planner_mode or "deterministic",
        pii_policy="redact",
        actor_user_id=user.id,
    )
    emitter.emit(
        EventType.RUN_RESUMED,
        f"Run retried by {user.username}",
        payload={"resume_source": "retry", "username": user.username},
        actor="user",
    )

    # Same-run retry: resets status, preserves history, commits — also
    # flushes the buffered event in the same transaction.
    service.retry(run_id)

    # Refresh run state after service mutation
    run = service.uow.runs.get(run_id)
    if not run:
        raise NotFoundError(f"Run not found after retry: {run_id}")

    # Schedule the same run for re-execution
    scheduler = get_scheduler()
    scheduler.schedule(run_id)

    return RetryRunResponse(
        run_id=run.id,
        status=run.status,
    )


@router.get("/{run_id}/compliance", response_model=ComplianceReportResponse)
async def get_compliance_report(
    run_id: str,
    service: RunServiceDep,
    _user: CurrentUserDep,
) -> ComplianceReportResponse:
    """Generate compliance audit report for a run."""
    # Access Run model directly
    assert service.uow.runs is not None
    run = service.uow.runs.get(run_id)
    if not run:
        raise NotFoundError(f"Run not found: {run_id}")

    # Generate compliance report from run data
    total_tokens = sum(s.tokens or 0 for s in run.steps) if run.steps else 0
    total_cost = sum(s.cost_usd or 0.0 for s in run.steps) if run.steps else 0.0

    report = {
        "run_id": run_id,
        "flow_id": run.flow_id,
        "status": run.status,
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost,
        "steps_analyzed": len(run.steps) if run.steps else 0,
        "compliance_score": 1.0 if run.status == "completed" else 0.5,
        "findings": [],
        "recommendations": [],
    }

    return ComplianceReportResponse(
        run_id=run_id,
        report=report,
    )
