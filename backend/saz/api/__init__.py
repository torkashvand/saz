"""Clean v1 API with Repository + UnitOfWork + Service architecture."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from typing import Any

from fastapi import Depends, FastAPI, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from saz.api.errors import (
    NotFoundError,
    ServiceError,
    generic_error_handler,
    service_error_handler,
    value_error_handler,
)
from saz.api.websocket import broadcast_events, websocket_endpoint
from saz.db.dependencies import get_uow
from saz.db.unit_of_work import UnitOfWork
from saz.engine.scheduler import get_scheduler
from saz.globals import initialize_globals
from saz.services.credential_service import CredentialService
from saz.services.flow_service import FlowService
from saz.services.run_service import RunService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown using FastAPI lifespan (replaces deprecated on_event)."""
    database_url = os.environ.get("DATABASE_URL")

    # Initialize global singletons
    initialize_globals(
        planner_model=os.environ.get("PLANNER_MODEL", "gpt-4o"),
        critic_model=os.environ.get("CRITIC_MODEL", "gpt-4o"),
    )

    if database_url:
        # Initialize scheduler on startup
        get_scheduler(database_url)
    yield
    # Shutdown scheduler gracefully
    try:
        scheduler = get_scheduler()
        scheduler.shutdown(wait=False)
    except Exception:
        pass


# Create app (with lifespan)
app = FastAPI(
    title="Saz Workflow API",
    version="2.0.0",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
    lifespan=lifespan,
)

# Exception handlers
app.add_exception_handler(ServiceError, service_error_handler)
app.add_exception_handler(ValueError, value_error_handler)
app.add_exception_handler(Exception, generic_error_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== Request/Response Models ==========


class CredentialType(str, Enum):
    """Valid credential types."""

    API_TOKEN = "api_token"
    PASSWORD = "password"
    SSH_KEY = "ssh_key"
    OAUTH = "oauth"
    CERTIFICATE = "certificate"


class RegisterFlowRequest(BaseModel):
    yaml: str


class WorkflowSummary(BaseModel):
    steps_count: int
    ai_steps: int
    credentials: list[str]


class RegisterFlowResponse(BaseModel):
    id: str
    name: str
    version: str | None = None
    description: str | None = None
    created_at: str
    workflow_summary: WorkflowSummary
    form_schema: dict


class FlowListResponse(BaseModel):
    items: list[dict]
    total: int


class CreateRunRequest(BaseModel):
    flow_id: str
    payload: dict


class CreateRunResponse(BaseModel):
    id: str
    flow_id: str
    status: str


class RunListResponse(BaseModel):
    items: list[dict]
    total: int


class RetryRunResponse(BaseModel):
    original_run_id: str
    new_run_id: str


class ReplayRunResponse(BaseModel):
    original_run_id: str
    new_run_id: str
    from_step: int


class CreateCredentialRequest(BaseModel):
    name: str
    credential_type: CredentialType
    data: dict
    description: str | None = None

    @field_validator("credential_type", mode="before")
    @classmethod
    def validate_credential_type(cls, v: str) -> str:
        """Validate credential type against enum values."""
        valid_types = [t.value for t in CredentialType]
        if v not in valid_types:
            raise ValueError(
                f"Invalid credential type: '{v}'. Must be one of: {', '.join(valid_types)}"
            )
        return v


class UpdateCredentialRequest(BaseModel):
    data: dict
    description: str | None = None


class CredentialResponse(BaseModel):
    name: str
    type: str


class CompileFlowRequest(BaseModel):
    yaml: str


class CompileFlowResponse(BaseModel):
    flow_name: str
    flow_version: str | None = None
    flow_description: str | None = None
    form_schema: dict
    workflow_summary: WorkflowSummary
    warnings: list[str] = []


# ========== Flow Endpoints ==========


@app.get("/api/v1/flows", response_model=FlowListResponse)
def list_flows(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    uow: UnitOfWork = Depends(get_uow),
) -> FlowListResponse:
    """List all flows."""
    service = FlowService(uow)
    items, total = service.list(limit, offset)

    return FlowListResponse(
        items=[
            {
                "id": item.id,
                "name": item.name,
                "version": item.version,
                "description": item.description,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ],
        total=total,
    )


@app.post("/api/v1/flows/compile", response_model=CompileFlowResponse)
def compile_flow(req: CompileFlowRequest) -> CompileFlowResponse:
    """Compile and validate YAML DSL without registering.

    This endpoint tests YAML validity, form schema generation,
    and workflow structure before registration.
    """
    from saz.compiler import compile_dsl

    try:
        compiled = compile_dsl(req.yaml)

        # Extract workflow info
        workflow_steps = compiled.workflow_spec.get("steps", [])
        ai_steps_count = sum(1 for step in workflow_steps if step.get("type", "").startswith("ai."))

        workflow_summary = WorkflowSummary(
            steps_count=len(workflow_steps),
            ai_steps=ai_steps_count,
            credentials=compiled.credentials,
        )

        return CompileFlowResponse(
            flow_name=compiled.flow_name,
            flow_version=compiled.flow_version,
            flow_description=compiled.flow_description,
            form_schema=compiled.form_schema,
            workflow_summary=workflow_summary,
            warnings=compiled.warnings,
        )
    except ValueError as e:
        raise ValueError(f"Compilation failed: {str(e)}") from None


@app.post("/api/v1/flows", response_model=RegisterFlowResponse)
def register_flow(
    req: RegisterFlowRequest, uow: UnitOfWork = Depends(get_uow)
) -> RegisterFlowResponse:
    """Register a new flow from YAML DSL."""
    from saz.compiler import compile_dsl

    # Compile YAML first (validates structure)
    try:
        compiled = compile_dsl(req.yaml)
    except ValueError as e:
        raise ValueError(f"Invalid flow definition: {str(e)}") from None

    # Register flow with compiled artifacts
    service = FlowService(uow)
    flow_id = service.register(req.yaml)
    flow_detail = service.get(flow_id)

    if not flow_detail:
        raise NotFoundError("Flow was created but not found")

    # Use compiled workflow summary
    workflow_steps = compiled.workflow_spec.get("steps", [])
    workflow_summary = WorkflowSummary(
        steps_count=len(workflow_steps),
        ai_steps=sum(1 for step in workflow_steps if step.get("type", "").startswith("ai.")),
        credentials=compiled.credentials,
    )

    return RegisterFlowResponse(
        id=flow_id,
        name=flow_detail.name,
        version=flow_detail.version,
        description=flow_detail.description,
        created_at=flow_detail.created_at.isoformat(),
        workflow_summary=workflow_summary,
        form_schema=compiled.form_schema,
    )


@app.get("/api/v1/flows/{id}")
def get_flow(id: str, uow: UnitOfWork = Depends(get_uow)) -> dict[str, Any]:
    """Get flow detail."""
    service = FlowService(uow)
    flow = service.get(id)

    if not flow:
        raise NotFoundError(f"Flow not found: {id}")

    return {
        "id": flow.id,
        "name": flow.name,
        "version": flow.version,
        "description": flow.description,
        "definition": flow.definition,
        "created_at": flow.created_at.isoformat(),
    }


@app.get("/api/v1/flows/{id}/graph")
def get_flow_graph(id: str, uow: UnitOfWork = Depends(get_uow)) -> dict[str, Any]:
    """Get flow graph visualization data."""
    service = FlowService(uow)
    flow = service.get(id)

    if not flow:
        raise NotFoundError(f"Flow not found: {id}")

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

        # Create linear edges (each step to next)
        if idx > 0:
            prev_step_id = workflow_steps[idx - 1].get("id", f"step_{idx - 1}")
            edges.append({"from": prev_step_id, "to": step_id})

    return {"nodes": nodes, "edges": edges}


# ========== Run Endpoints ==========


@app.get("/api/v1/runs", response_model=RunListResponse)
def list_runs(
    flow_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    uow: UnitOfWork = Depends(get_uow),
) -> RunListResponse:
    """List runs with optional filters."""
    service = RunService(uow)
    items, total = service.list(flow_id, status, limit, offset)

    return RunListResponse(
        items=[
            {
                "id": item.id,
                "flow_id": item.flow_id,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                "cost_cents": item.cost_cents,
            }
            for item in items
        ],
        total=total,
    )


@app.post("/api/v1/runs", response_model=CreateRunResponse)
async def create_run(
    req: CreateRunRequest, uow: UnitOfWork = Depends(get_uow)
) -> CreateRunResponse | JSONResponse:
    """Create a new run and schedule it for immediate execution."""
    service = RunService(uow)
    run_id = service.create(req.flow_id, req.payload)

    # Broadcast run.started event
    events = uow.collect_events()
    await broadcast_events(events)

    # Atomically mark as running and schedule execution
    assert uow.runs is not None
    run = uow.runs.mark_running(run_id)
    if not run:
        return JSONResponse(
            status_code=500,
            content={
                "error": "InternalError",
                "message": "Failed to mark run as running",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    uow.commit()

    # Schedule for execution in thread pool
    scheduler = get_scheduler()
    scheduled = scheduler.schedule(run_id)
    if not scheduled:
        return JSONResponse(
            status_code=409,
            content={
                "error": "AlreadyRunning",
                "message": f"Run {run_id} is already scheduled or running",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    return CreateRunResponse(id=run_id, flow_id=req.flow_id, status="running")


@app.get("/api/v1/runs/{id}")
def get_run(id: str, uow: UnitOfWork = Depends(get_uow)) -> dict[str, Any]:
    """Get run detail."""
    service = RunService(uow)
    run = service.get(id)

    if not run:
        raise NotFoundError(f"Run not found: {id}")

    # Compute totals
    cost_usd = run.cost_cents / 100.0 if run.cost_cents else 0.0

    return {
        "id": run.id,
        "run_id": run.id,
        "flow_id": run.flow_id,
        "flow_name": run.flow_name,
        "status": run.status,
        "payload": run.payload,
        "error": run.error,
        "cost_cents": run.cost_cents,
        "created_at": run.created_at.isoformat(),
        "started_at": run.created_at.isoformat(),  # Use created_at as started_at
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "totals": {
            "tokens": 0,  # Not tracked yet
            "cost_usd": cost_usd,
        },
        "steps": [
            {
                "id": s.name,  # Use name as id for frontend
                "number": s.number,
                "name": s.name,
                "type": "unknown",  # Not tracked in current schema
                "status": s.status,
                "start_ts": s.start_ts.isoformat() if s.start_ts else None,
                "end_ts": s.end_ts.isoformat() if s.end_ts else None,
                "duration_ms": s.duration_ms,
                "retry_count": s.retry_count,
                "error": s.error,
                "tokens": 0,  # Not tracked yet
                "cost_usd": 0.0,  # Not tracked yet
                "input": None,  # Not tracked yet
                "output": s.output,
                "failure": {"type": "error", "message": s.error.get("message", "Unknown error")}
                if s.error
                else None,
            }
            for s in run.steps
        ],
        "artifacts": [],  # Not tracked yet, use artifact_count
        "artifact_count": run.artifact_count,
    }


@app.get("/api/v1/runs/{id}/steps")
def get_run_steps(id: str, uow: UnitOfWork = Depends(get_uow)) -> dict[str, Any]:
    """Get run steps."""
    service = RunService(uow)
    run = service.get(id)

    if not run:
        raise NotFoundError(f"Run not found: {id}")

    return {
        "run_id": run.id,
        "steps": [
            {
                "id": s.id,
                "number": s.number,
                "name": s.name,
                "status": s.status,
                "start_ts": s.start_ts.isoformat() if s.start_ts else None,
                "end_ts": s.end_ts.isoformat() if s.end_ts else None,
                "duration_ms": s.duration_ms,
                "retry_count": s.retry_count,
                "output": s.output,
                "error": s.error,
            }
            for s in run.steps
        ],
    }


@app.get("/api/v1/runs/{id}/graph")
def get_run_graph(id: str, uow: UnitOfWork = Depends(get_uow)) -> dict[str, Any]:
    """Get run graph visualization with step status overlay."""
    service = RunService(uow)
    run = service.get(id)

    if not run:
        raise NotFoundError(f"Run not found: {id}")

    # Get flow to build graph structure
    flow_service = FlowService(uow)
    flow = flow_service.get(run.flow_id)

    if not flow:
        raise NotFoundError(f"Flow not found: {run.flow_id}")

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

        # Create linear edges (each step to next)
        if idx > 0:
            prev_step_id = workflow_steps[idx - 1].get("id", f"step_{idx - 1}")
            edges.append({"from": prev_step_id, "to": step_id})

    # Build status map from run steps
    status_by_step = {s.name: s.status for s in run.steps}

    return {"nodes": nodes, "edges": edges, "status_by_step": status_by_step}


@app.post("/api/v1/runs/{id}/retry", response_model=RetryRunResponse)
async def retry_run(id: str, uow: UnitOfWork = Depends(get_uow)) -> RetryRunResponse:
    """Retry a failed run."""
    service = RunService(uow)
    new_run_id = service.retry(id)

    # Broadcast events
    events = uow.collect_events()
    await broadcast_events(events)

    return RetryRunResponse(original_run_id=id, new_run_id=new_run_id)


@app.post("/api/v1/runs/{id}/replay", response_model=ReplayRunResponse)
async def replay_run(
    id: str, from_step: int = Query(0, ge=0), uow: UnitOfWork = Depends(get_uow)
) -> ReplayRunResponse:
    """Replay a run from a specific step."""
    service = RunService(uow)
    new_run_id = service.replay(id, from_step)

    # Broadcast events
    events = uow.collect_events()
    await broadcast_events(events)

    return ReplayRunResponse(original_run_id=id, new_run_id=new_run_id, from_step=from_step)


@app.get("/api/v1/runs/{id}/compliance")
def get_run_compliance(id: str, uow: UnitOfWork = Depends(get_uow)) -> dict[str, Any]:
    """
    Get compliance report for a run.

    Returns per-step and total tokens, cost, policy violations, and budget status.
    """
    service = RunService(uow)
    run = service.get(id)

    if not run:
        raise NotFoundError(f"Run not found: {id}")

    # Aggregate per-step metrics
    step_metrics = []
    total_tokens = 0
    total_cost = 0.0

    for step in run.steps:
        tokens = step.tokens or 0
        cost = step.cost_usd or 0.0
        total_tokens += tokens
        total_cost += cost

        step_metrics.append(
            {
                "step_id": step.name,
                "step_number": step.number,
                "tokens": tokens,
                "cost_usd": cost,
                "policy_flags": step.policy_flags,
                "critique": step.critique,
            }
        )

    # Get policy engine status (if run is still active)
    from saz.globals import get_policy_engine

    policy_engine = get_policy_engine()

    try:
        compliance_report = policy_engine.get_compliance_report(id)
    except Exception:
        # Run may not be tracked in policy engine (completed/old run)
        compliance_report = {
            "run_id": id,
            "budget": {"note": "Run completed, budget tracker cleared"},
            "rate_limits": {},
            "policies_enforced": {},
        }

    return {
        "run_id": id,
        "status": run.status,
        "totals": {
            "tokens": total_tokens,
            "cost_usd": total_cost,
            "steps": len(run.steps),
        },
        "steps": step_metrics,
        "policy_report": compliance_report,
    }


# ========== Credential Endpoints ==========


@app.get("/api/v1/credentials")
def list_credentials(uow: UnitOfWork = Depends(get_uow)) -> dict[str, Any]:
    """List all credentials (metadata only)."""
    service = CredentialService(uow)
    items = service.list()

    return {
        "items": [
            {
                "name": item.name,
                "type": item.type,
                "description": item.description,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            }
            for item in items
        ],
        "total": len(items),
    }


@app.post("/api/v1/credentials", response_model=CredentialResponse)
def create_credential(
    req: CreateCredentialRequest, uow: UnitOfWork = Depends(get_uow)
) -> CredentialResponse:
    """Create a new credential."""
    service = CredentialService(uow)
    name = service.create(req.name, req.credential_type, req.data, req.description)

    return CredentialResponse(name=name, type=req.credential_type)


@app.put("/api/v1/credentials/{name}", response_model=CredentialResponse)
def update_credential(
    name: str, req: UpdateCredentialRequest, uow: UnitOfWork = Depends(get_uow)
) -> CredentialResponse:
    """Update a credential."""
    service = CredentialService(uow)

    # Get existing to return type
    assert service.uow.credentials is not None
    existing = service.uow.credentials.get(name)
    if not existing:
        raise NotFoundError(f"Credential not found: {name}")

    service.update(name, req.data, req.description)

    return CredentialResponse(name=name, type=existing.type)


@app.delete("/api/v1/credentials/{name}")
def delete_credential(name: str, uow: UnitOfWork = Depends(get_uow)) -> dict[str, Any]:
    """Delete a credential."""
    service = CredentialService(uow)
    success = service.delete(name)

    if not success:
        raise NotFoundError(f"Credential not found: {name}")

    return {"status": "deleted", "name": name}


# ========== Webhook & Resume Endpoints ==========


@app.post("/api/v1/webhooks/{event_name}")
async def trigger_webhook(
    event_name: str,
    payload: dict,
    uow: UnitOfWork = Depends(get_uow),
) -> dict[str, Any]:
    """
    Trigger webhook event to resume waiting runs.

    Matches runs waiting on webhook.wait with this event_name.
    """
    # Find suspended runs waiting for this webhook
    assert uow.run_reads is not None
    runs = uow.run_reads.list(status="suspended", limit=1000, offset=0)[0]

    resumed_count = 0
    for run in runs:
        # Check if run is waiting for this webhook
        # (This requires storing webhook wait state in run.error field)
        if run.error and run.error.get("type") == "WebhookWait":
            expected_event = run.error.get("event_name")
            if expected_event == event_name:
                # Resume run by scheduling execution
                # Store webhook payload in run.payload under special key
                assert uow.runs is not None
                db_run = uow.runs.get(run.id)
                if db_run:
                    db_run.payload["_webhook_data"] = {event_name: payload}
                    db_run.status = "queued"
                    uow.commit()

                    # Schedule for execution
                    scheduler = get_scheduler()
                    scheduler.schedule(run.id)
                    resumed_count += 1

    return {
        "event_name": event_name,
        "resumed_runs": resumed_count,
        "status": "triggered",
    }


@app.post("/api/v1/runs/{id}/resume", response_model=None)
async def resume_run(
    id: str,
    payload: dict[str, Any] | None = None,
    uow: UnitOfWork = Depends(get_uow),
) -> dict[str, Any] | JSONResponse:
    """
    Resume a suspended run (e.g., after human approval).

    Optionally accepts payload to merge into run state.
    """
    service = RunService(uow)
    run = service.get(id)

    if not run:
        raise NotFoundError(f"Run not found: {id}")

    if run.status != "suspended":
        raise ValueError(f"Can only resume suspended runs, got: {run.status}")

    # Merge payload if provided
    assert uow.runs is not None
    db_run = uow.runs.get(id)
    if not db_run:
        raise NotFoundError(f"Run not found: {id}")

    if payload:
        db_run.payload.update(payload)

    # Mark as queued and schedule
    db_run.status = "queued"
    db_run.error = None  # Clear suspension reason
    uow.commit()

    scheduler = get_scheduler()
    scheduled = scheduler.schedule(id)

    if not scheduled:
        return JSONResponse(
            status_code=409,
            content={
                "error": "AlreadyRunning",
                "message": f"Run {id} is already scheduled or running",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    return {
        "run_id": id,
        "status": "resumed",
        "scheduled": True,
    }


# ========== WebSocket ==========


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket) -> None:
    """Global WebSocket endpoint for all domain events."""
    await websocket_endpoint(websocket)


# ========== Health ==========


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "Saz Workflow API", "version": "2.0.0"}
