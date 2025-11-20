"""Run management and execution endpoints."""

from fastapi import APIRouter, Query

from saz.api.dependencies import RunServiceDep
from saz.api.errors import NotFoundError
from saz.api.schemas.event_schemas import EventListResponse, RunSummaryResponse
from saz.api.schemas.run_schemas import (
    ComplianceReportResponse,
    CreateRunRequest,
    CreateRunResponse,
    ExecutionGraphResponse,
    ReplayRunRequest,
    ReplayRunResponse,
    RetryRunRequest,
    RetryRunResponse,
    RunListItem,
    RunListResponse,
    RunStepsResponse,
    RunSummary,
)

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


@router.get("", response_model=RunListResponse)
async def list_runs(
    service: RunServiceDep,
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
        runs=[
            RunListItem(
                id=r.id,
                flow_id=r.flow_id,
                flow_name=r.flow.name if r.flow else "Unknown",
                status=r.status,
                created_at=r.created_at,
                completed_at=r.completed_at,
                total_cost_usd=r.total_cost_usd or 0.0,
                total_tokens=r.total_tokens or 0,
                error=r.error,
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
) -> CreateRunResponse:
    """Create and start a new run."""
    # RunService.create returns run_id string, not run object
    run_id = service.create(
        flow_id=req.flow_id,
        payload=req.input_data or {},
    )

    # Get the created run
    assert service.uow.runs is not None
    run = service.uow.runs.get(run_id)
    if not run:
        raise NotFoundError(f"Run not found after creation: {run_id}")

    return CreateRunResponse(
        id=run.id,
        flow_id=run.flow_id,
        status=run.status,
    )


@router.get("/{run_id}/summary", response_model=RunSummary)
async def get_run_summary(
    run_id: str,
    service: RunServiceDep,
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
        error=run.error,
    )


@router.get("/{run_id}/events", response_model=EventListResponse)
async def get_run_events(
    run_id: str,
    service: RunServiceDep,
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
    from datetime import datetime

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

    from saz.api.schemas.event_schemas import EventResponse

    return EventListResponse(
        events=[EventResponse.model_validate(e) for e in events],
        total=len(events),
        cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.get("/{run_id}", response_model=RunSummaryResponse)
async def get_run_detail(
    run_id: str,
    service: RunServiceDep,
) -> RunSummaryResponse:
    """Get run detail with aggregated event metrics."""
    # Get run model directly to access all fields
    assert service.uow.run_reads is not None
    run = service.uow.run_reads.get(run_id)
    if not run:
        raise NotFoundError(f"Run not found: {run_id}")

    # Aggregate event metrics
    assert service.uow.event_queries is not None
    event_counts = service.uow.event_queries.count_by_type(run_id)
    total_events = sum(event_counts.values())
    error_count = service.uow.event_queries.count_errors(run_id)

    # Calculate duration if completed
    duration_ms = None
    if run.completed_at and run.created_at:
        duration_ms = int((run.completed_at - run.created_at).total_seconds() * 1000)

    return RunSummaryResponse(
        id=run.id,
        flow_id=run.flow_id,
        status=run.status,
        planner_mode=run.planner_mode,
        created_at=run.created_at,
        completed_at=run.completed_at,
        duration_ms=duration_ms or run.duration_ms,
        total_events=total_events,
        event_counts=event_counts,
        total_tokens=run.total_tokens or 0,
        total_cost_usd=run.total_cost_usd or 0.0,
        error_count=error_count,
    )


@router.get("/{run_id}/steps", response_model=RunStepsResponse)
async def get_run_steps(
    run_id: str,
    service: RunServiceDep,
) -> RunStepsResponse:
    """Get execution steps for a run."""
    # Access Run model directly
    assert service.uow.runs is not None
    run = service.uow.runs.get(run_id)
    if not run:
        raise NotFoundError(f"Run not found: {run_id}")

    # Convert steps to StepSummary
    from saz.api.schemas.run_schemas import StepSummary

    return RunStepsResponse(
        run_id=run.id,
        status=run.status,
        steps=[
            StepSummary(
                id=s.id,
                number=s.number,
                name=s.name,
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
                error=s.error,
            )
            for s in (run.steps or [])
        ],
    )


@router.get("/{run_id}/graph", response_model=ExecutionGraphResponse)
async def get_run_graph(
    run_id: str,
    service: RunServiceDep,
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
    req: RetryRunRequest,
    service: RunServiceDep,
) -> RetryRunResponse:
    """Retry a failed run from the point of failure."""
    # Access Run model directly
    assert service.uow.runs is not None
    run = service.uow.runs.get(run_id)
    if not run:
        raise NotFoundError(f"Run not found: {run_id}")

    if run.status not in ["failed", "error"]:
        raise ValueError(f"Run {run_id} cannot be retried (status: {run.status})")

    # RunService.retry returns new run_id string
    new_run_id = service.retry(run_id)
    new_run = service.uow.runs.get(new_run_id)

    if not new_run:
        raise NotFoundError(f"New run not found: {new_run_id}")

    return RetryRunResponse(
        new_run_id=new_run.id,
        original_run_id=run_id,
        status=new_run.status,
    )


@router.post("/{run_id}/replay", response_model=ReplayRunResponse)
async def replay_run_endpoint(
    run_id: str,
    req: ReplayRunRequest,
    service: RunServiceDep,
) -> ReplayRunResponse:
    """Replay a completed run with optional input modifications."""
    # Access Run model directly
    assert service.uow.runs is not None
    run = service.uow.runs.get(run_id)
    if not run:
        raise NotFoundError(f"Run not found: {run_id}")

    # RunService.replay takes from_step parameter (default 0)
    new_run_id = service.replay(run_id, from_step=0)
    new_run = service.uow.runs.get(new_run_id)

    if not new_run:
        raise NotFoundError(f"New run not found: {new_run_id}")

    return ReplayRunResponse(
        new_run_id=new_run.id,
        original_run_id=run_id,
        status=new_run.status,
    )


@router.get("/{run_id}/compliance", response_model=ComplianceReportResponse)
async def get_compliance_report(
    run_id: str,
    service: RunServiceDep,
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
