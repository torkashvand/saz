"""Clean v1 API with Repository + UnitOfWork + Service architecture."""
from typing import Optional
from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from saz.db.dependencies import get_uow
from saz.db.unit_of_work import UnitOfWork
from saz.services.run_service import RunService
from saz.services.flow_service import FlowService
from saz.services.credential_service import CredentialService
from saz.api.errors import (
    ServiceError,
    NotFoundError,
    service_error_handler,
    value_error_handler,
    generic_error_handler
)

# Create app
app = FastAPI(
    title="Saz Workflow API",
    version="2.0.0",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json"
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

class RegisterFlowRequest(BaseModel):
    yaml: str


class RegisterFlowResponse(BaseModel):
    id: str
    name: str


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
    credential_type: str
    data: dict
    description: Optional[str] = None


class UpdateCredentialRequest(BaseModel):
    data: dict
    description: Optional[str] = None


class CredentialResponse(BaseModel):
    name: str
    type: str


# ========== Flow Endpoints ==========

@app.get("/api/v1/flows", response_model=FlowListResponse)
def list_flows(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    uow: UnitOfWork = Depends(get_uow)
):
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
                "created_at": item.created_at.isoformat()
            }
            for item in items
        ],
        total=total
    )


@app.post("/api/v1/flows", response_model=RegisterFlowResponse)
def register_flow(req: RegisterFlowRequest, uow: UnitOfWork = Depends(get_uow)):
    """Register a new flow from YAML DSL."""
    service = FlowService(uow)
    flow_id = service.register(req.yaml)
    flow_detail = service.get(flow_id)

    if not flow_detail:
        raise NotFoundError("Flow was created but not found")

    return RegisterFlowResponse(id=flow_id, name=flow_detail.name)


@app.get("/api/v1/flows/{id}")
def get_flow(id: str, uow: UnitOfWork = Depends(get_uow)):
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
        "created_at": flow.created_at.isoformat()
    }


# ========== Run Endpoints ==========

@app.get("/api/v1/runs", response_model=RunListResponse)
def list_runs(
    flow_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    uow: UnitOfWork = Depends(get_uow)
):
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
                "cost_cents": item.cost_cents
            }
            for item in items
        ],
        total=total
    )


@app.post("/api/v1/runs", response_model=CreateRunResponse)
def create_run(req: CreateRunRequest, uow: UnitOfWork = Depends(get_uow)):
    """Create a new run."""
    service = RunService(uow)
    run_id = service.create(req.flow_id, req.payload)

    return CreateRunResponse(
        id=run_id,
        flow_id=req.flow_id,
        status="queued"
    )


@app.get("/api/v1/runs/{id}")
def get_run(id: str, uow: UnitOfWork = Depends(get_uow)):
    """Get run detail."""
    service = RunService(uow)
    run = service.get(id)

    if not run:
        raise NotFoundError(f"Run not found: {id}")

    return {
        "id": run.id,
        "flow_id": run.flow_id,
        "flow_name": run.flow_name,
        "status": run.status,
        "payload": run.payload,
        "error": run.error,
        "cost_cents": run.cost_cents,
        "created_at": run.created_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
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
                "error": s.error
            }
            for s in run.steps
        ],
        "artifact_count": run.artifact_count
    }


@app.get("/api/v1/runs/{id}/steps")
def get_run_steps(id: str, uow: UnitOfWork = Depends(get_uow)):
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
                "error": s.error
            }
            for s in run.steps
        ]
    }


@app.post("/api/v1/runs/{id}/retry", response_model=RetryRunResponse)
def retry_run(id: str, uow: UnitOfWork = Depends(get_uow)):
    """Retry a failed run."""
    service = RunService(uow)
    new_run_id = service.retry(id)

    return RetryRunResponse(
        original_run_id=id,
        new_run_id=new_run_id
    )


@app.post("/api/v1/runs/{id}/replay", response_model=ReplayRunResponse)
def replay_run(
    id: str,
    from_step: int = Query(0, ge=0),
    uow: UnitOfWork = Depends(get_uow)
):
    """Replay a run from a specific step."""
    service = RunService(uow)
    new_run_id = service.replay(id, from_step)

    return ReplayRunResponse(
        original_run_id=id,
        new_run_id=new_run_id,
        from_step=from_step
    )


# ========== Credential Endpoints ==========

@app.get("/api/v1/credentials")
def list_credentials(uow: UnitOfWork = Depends(get_uow)):
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
                "updated_at": item.updated_at.isoformat()
            }
            for item in items
        ],
        "total": len(items)
    }


@app.post("/api/v1/credentials", response_model=CredentialResponse)
def create_credential(req: CreateCredentialRequest, uow: UnitOfWork = Depends(get_uow)):
    """Create a new credential."""
    service = CredentialService(uow)
    name = service.create(req.name, req.credential_type, req.data, req.description)

    return CredentialResponse(name=name, type=req.credential_type)


@app.put("/api/v1/credentials/{name}", response_model=CredentialResponse)
def update_credential(
    name: str,
    req: UpdateCredentialRequest,
    uow: UnitOfWork = Depends(get_uow)
):
    """Update a credential."""
    service = CredentialService(uow)

    # Get existing to return type
    existing = service.uow.credentials.get(name)
    if not existing:
        raise NotFoundError(f"Credential not found: {name}")

    service.update(name, req.data, req.description)

    return CredentialResponse(name=name, type=existing.type)


@app.delete("/api/v1/credentials/{name}")
def delete_credential(name: str, uow: UnitOfWork = Depends(get_uow)):
    """Delete a credential."""
    service = CredentialService(uow)
    success = service.delete(name)

    if not success:
        raise NotFoundError(f"Credential not found: {name}")

    return {"status": "deleted", "name": name}


# ========== Health ==========

@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/")
def root():
    return {"name": "Saz Workflow API", "version": "2.0.0"}
