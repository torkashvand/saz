"""Flow management endpoints."""

from fastapi import APIRouter, Query

from saz.api.dependencies import FlowServiceDep
from saz.api.errors import NotFoundError
from saz.api.schemas.flow_schemas import (
    CompileFlowRequest,
    CompileFlowResponse,
    FlowDetail,
    FlowGraphResponse,
    FlowListItem,
    FlowListResponse,
    RegisterFlowRequest,
    RegisterFlowResponse,
    WorkflowPolicies,
)

router = APIRouter(prefix="/api/v1/flows", tags=["flows"])


@router.get("", response_model=FlowListResponse)
async def list_flows(
    service: FlowServiceDep,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> FlowListResponse:
    """List all registered flows."""
    flows, total = service.list(limit=limit, offset=offset)

    return FlowListResponse(
        flows=[
            FlowListItem(
                id=f.id,
                name=f.name,
                version=f.version,
                description=f.description,
                created_at=f.created_at,
            )
            for f in flows
        ],
        total=total,
    )


@router.post("", response_model=RegisterFlowResponse)
async def register_flow(
    req: RegisterFlowRequest,
    service: FlowServiceDep,
) -> RegisterFlowResponse:
    """Register a new flow from YAML definition."""
    flow_id = service.register(req.yaml)
    flow = service.get(flow_id)

    if not flow:
        raise NotFoundError(f"Flow not found after registration: {flow_id}")

    return RegisterFlowResponse(
        id=flow.id,
        name=flow.name,
        version=flow.version,
    )


@router.post("/compile", response_model=CompileFlowResponse)
async def compile_flow(
    req: CompileFlowRequest,
    service: FlowServiceDep,
) -> CompileFlowResponse:
    """Compile and validate a flow YAML without persisting."""
    from saz.api.schemas.flow_schemas import WorkflowSummary
    from saz.compiler import compile_dsl

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


@router.get("/{flow_id}", response_model=FlowDetail)
async def get_flow(
    flow_id: str,
    service: FlowServiceDep,
) -> FlowDetail:
    """Get detailed flow information."""
    flow = service.get(flow_id)
    if not flow:
        raise NotFoundError(f"Flow not found: {flow_id}")

    workflow_def = flow.definition.get("workflow", {})
    policies_def = workflow_def.get("policies", {})

    return FlowDetail(
        id=flow.id,
        name=flow.name,
        version=flow.version,
        description=flow.description,
        definition=flow.definition,
        planner_mode=workflow_def.get("planner_mode", "deterministic"),
        policies=WorkflowPolicies(
            max_steps=policies_def.get("max_steps", 50),
            max_cost_usd=policies_def.get("max_cost_usd", 10.0),
            max_tokens=policies_def.get("max_tokens", 100000),
        ),
        step_count=len(flow.definition.get("steps", [])),
        created_at=flow.created_at,
    )


@router.get("/{flow_id}/graph", response_model=FlowGraphResponse)
async def get_flow_graph(
    flow_id: str,
    service: FlowServiceDep,
) -> FlowGraphResponse:
    """Get flow execution graph (nodes and edges)."""
    flow = service.get(flow_id)
    if not flow:
        raise NotFoundError(f"Flow not found: {flow_id}")

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

    return FlowGraphResponse(
        nodes=nodes,
        edges=edges,
    )
