"""Flow management endpoints."""

from fastapi import APIRouter, Query

from saz.api.dependencies import CurrentUserDep, FlowServiceDep
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
    WorkflowSummary,
)
from saz.compiler import compile_dsl

router = APIRouter(prefix="/api/v1/flows", tags=["flows"])


@router.get("", response_model=FlowListResponse)
async def list_flows(
    service: FlowServiceDep,
    _user: CurrentUserDep,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> FlowListResponse:
    """List all registered flows."""
    flows, total = service.list(limit=limit, offset=offset)

    return FlowListResponse(
        items=[
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
    user: CurrentUserDep,
) -> RegisterFlowResponse:
    """Register a new flow from YAML definition."""
    flow_id = service.register(req.yaml, created_by_user_id=user.id)
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
    _user: CurrentUserDep,
) -> CompileFlowResponse:
    """Compile and validate a flow YAML without persisting."""
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


@router.get("/ai-ops")
async def list_ai_ops(_user: CurrentUserDep) -> list[dict]:
    """Return available AI operations with their default output schemas.

    Helps workflow authors write correct `expect` fields by showing
    what each AI operation produces and what extras it accepts.
    """
    from saz.agents.ai_ops import AI_OPS

    ops = []
    for name, spec in AI_OPS.items():
        if name == "ai.fix_json":
            continue  # internal repair tool, not user-facing
        ops.append(
            {
                "name": name,
                "description": spec.description,
                "output_format": spec.output_format,
                "default_output_schema": spec.default_expect_schema,
                "extras": {k: v for k, v in spec.input_extras.items()} if spec.input_extras else {},
            }
        )
    return ops


@router.get("/{flow_id}", response_model=FlowDetail)
async def get_flow(
    flow_id: str,
    service: FlowServiceDep,
    _user: CurrentUserDep,
) -> FlowDetail:
    """Get detailed flow information."""
    flow = service.get(flow_id)
    if not flow:
        raise NotFoundError(f"Flow not found: {flow_id}")

    workflow_def = flow.definition.get("workflow", {})
    # Policies are at root level in the stored YAML definition, not under workflow
    policies_def = flow.definition.get("policies", {})

    return FlowDetail(
        id=flow.id,
        name=flow.name,
        version=flow.version,
        description=flow.description,
        definition=flow.definition,
        original_yaml=flow.source_yaml,
        planner_mode=workflow_def.get("planner_mode", "deterministic"),
        policies=WorkflowPolicies(
            max_steps=policies_def.get("max_steps", 50),
            # DSL uses budget_usd, map to max_cost_usd for API response
            max_cost_usd=policies_def.get("budget_usd", 10.0),
            max_tokens=policies_def.get("max_tokens", 100000),
        ),
        # Steps are under workflow.steps, not at root
        step_count=len(workflow_def.get("steps", [])),
        created_at=flow.created_at,
    )


@router.get("/{flow_id}/graph", response_model=FlowGraphResponse)
async def get_flow_graph(
    flow_id: str,
    service: FlowServiceDep,
    _user: CurrentUserDep,
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
        step_label = step.get("instruction", step.get("description", step_id))

        nodes.append(
            {
                "id": step_id,
                "label": step_label[:50] + "..." if len(step_label) > 50 else step_label,
                "type": step_type,
            }
        )

        # Create linear edges (each step connects to the next)
        if idx > 0:
            prev_step = workflow_steps[idx - 1]
            prev_step_id = prev_step.get("id", f"step_{idx - 1}")
            prev_type = prev_step.get("type", "")

            # Add edge label for condition/route steps to indicate branching semantics
            edge_label = None
            if prev_type == "condition":
                edge_label = "true"
            elif prev_type == "ai.route":
                edge_label = "routed"

            edge: dict = {"from": prev_step_id, "to": step_id}
            if edge_label:
                edge["label"] = edge_label
            edges.append(edge)

    return FlowGraphResponse(
        nodes=nodes,
        edges=edges,
    )
