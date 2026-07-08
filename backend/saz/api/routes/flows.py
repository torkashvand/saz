"""Flow management endpoints."""

from typing import Any

from fastapi import APIRouter, Query

from saz.api.compile_errors import safe_compile_response
from saz.api.dependencies import CurrentUserDep, FlowServiceDep, OperatorUserDep
from saz.api.dsl_metadata import build_dsl_metadata
from saz.api.errors import NotFoundError
from saz.api.schemas.flow_schemas import (
    CompileFlowRequest,
    CompileFlowResponse,
    FlowDetail,
    FlowGraphResponse,
    FlowLintRequest,
    FlowLintResponse,
    FlowListItem,
    FlowListResponse,
    RegisterFlowRequest,
    RegisterFlowResponse,
    UpdateFlowRequest,
    WorkflowPolicies,
    WorkflowSummary,
)

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
                planner_mode=f.planner_mode,
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
    user: OperatorUserDep,
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
    """Compile and validate a flow YAML without persisting.

    On success: returns the normalized DSL plus a structured summary.
    On failure: returns valid=False with structured errors carrying section
    + step_id + JSON pointer so the Guided Builder can map them to the
    right card. We do not raise — the frontend renders errors inline.
    """

    compiled, errors = safe_compile_response(req.yaml)

    if errors or compiled is None:
        return CompileFlowResponse(
            valid=False,
            flow_name="",
            form_schema={},
            workflow_summary=WorkflowSummary(steps_count=0, ai_steps=0, credentials=[]),
            errors=errors,
        )

    workflow_steps = compiled.workflow_spec.get("steps", [])
    ai_steps_count = sum(1 for step in workflow_steps if step.get("type", "").startswith("ai."))
    workflow_summary = WorkflowSummary(
        steps_count=len(workflow_steps),
        ai_steps=ai_steps_count,
        credentials=compiled.credentials,
    )

    normalized = _build_normalized_dsl(compiled)

    return CompileFlowResponse(
        valid=True,
        flow_name=compiled.flow_name,
        flow_version=compiled.flow_version,
        flow_description=compiled.flow_description,
        form_schema=compiled.form_schema,
        workflow_summary=workflow_summary,
        warnings=compiled.warnings,
        normalized_dsl=normalized,
    )


@router.post("/lint", response_model=FlowLintResponse)
async def lint_flow_endpoint(
    req: FlowLintRequest,
    service: FlowServiceDep,
    _user: CurrentUserDep,
) -> FlowLintResponse:
    """Lint a flow YAML without persisting (powers live builder feedback).

    Compile errors are returned distinctly (``compile_error``) from lint
    findings. The save gate re-runs the same linter, so this preview cannot be
    bypassed.
    """
    try:
        report = service.lint(req.yaml)
    except ValueError as exc:
        return FlowLintResponse(valid=False, compile_error=str(exc))

    return FlowLintResponse(
        valid=not report.blocking,
        findings=report.findings,
        llm_ran=report.llm_ran,
    )


@router.get("/dsl-metadata")
async def dsl_metadata(_user: CurrentUserDep) -> dict[str, Any]:
    """Return the centralized DSL metadata payload.

    Used by the Guided Builder to render the right editors for each step
    type, populate the expression picker, and discover registered tools
    without hard-coding the DSL shape on the frontend.
    """

    return build_dsl_metadata()


def _build_normalized_dsl(compiled: Any) -> dict[str, Any]:
    """Project the compiler result into a canonical DSL document.

    The compiler keeps the canonical shape internally; we just surface it
    in one place so the frontend can build the draft from authoritative
    data instead of having to re-derive it from the raw YAML.
    """

    return {
        "schema_version": 1,
        "flow": {
            "name": compiled.flow_name,
            "version": compiled.flow_version,
            "description": compiled.flow_description,
        },
        "form_schema": compiled.form_schema,
        "workflow": compiled.workflow_spec,
        "credentials": {"uses": compiled.credentials},
        "warnings": compiled.warnings,
    }


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


@router.put("/{flow_id}", response_model=RegisterFlowResponse)
async def update_flow(
    flow_id: str,
    req: UpdateFlowRequest,
    service: FlowServiceDep,
    _user: OperatorUserDep,
) -> RegisterFlowResponse:
    """Update an existing flow by its ID.

    Differs from POST /flows in that this identifies the row by `flow_id`,
    not by the flow name in the YAML. That lets users safely rename a flow
    without creating a separate row.
    """

    try:
        updated_id = service.update_by_id(flow_id, req.yaml)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc

    flow = service.get(updated_id)
    if not flow:
        raise NotFoundError(f"Flow not found after update: {flow_id}")
    return RegisterFlowResponse(id=flow.id, name=flow.name, version=flow.version)


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
