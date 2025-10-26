"""Additional API endpoints for unified DSL support.

Add these to the main api.py file.
"""
from fastapi import HTTPException
from pydantic import BaseModel as PydanticBase
from saz.compiler import compile_dsl


class RegisterFlowRequest(PydanticBase):
    """Request for POST /flows/register"""
    yaml: str


class RegisterFlowResponse(PydanticBase):
    """Response for POST /flows/register"""
    flow_id: str
    name: str
    form_schema: dict
    workflow_summary: dict


class FlowGraphResponse(PydanticBase):
    """Response for GET /flows/{flow_id}/graph"""
    nodes: list[dict]
    edges: list[dict]


class RunGraphResponse(PydanticBase):
    """Response for GET /runs/{run_id}/graph"""
    nodes: list[dict]
    edges: list[dict]
    status: dict[str, str]  # step_id -> status


class EnhancedRunResponse(PydanticBase):
    """Enhanced response for GET /runs/{run_id}"""
    run_id: str
    flow_id: str
    status: str
    started_at: str
    completed_at: str | None
    current_state: dict
    totals: dict  # {tokens, cost_usd}
    steps: list[dict]  # Full step details
    artifacts: list[str]


# --- Endpoint Implementations ---


def register_flow_endpoint(req: RegisterFlowRequest, db: Session):
    """POST /flows/register - Register unified YAML DSL."""
    try:
        compiled = compile_dsl(req.yaml)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")

    # Check if flow already exists
    existing_flow = db.query(FlowTable).filter(FlowTable.name == compiled.flow_name).first()
    if existing_flow:
        # Update existing flow
        existing_flow.description = compiled.flow_description
        existing_flow.definition = {
            "dsl": compiled.raw_dsl,
            "workflow_spec": compiled.workflow_spec,
            "form_schema": compiled.form_schema,
            "policies": compiled.policies,
            "triggers": compiled.triggers,
            "credentials": compiled.credentials
        }
        existing_flow.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(existing_flow)

        return RegisterFlowResponse(
            flow_id=str(existing_flow.flow_id),
            name=compiled.flow_name,
            form_schema=compiled.form_schema,
            workflow_summary={
                "steps_count": len(compiled.workflow_spec["steps"]),
                "ai_steps": sum(1 for s in compiled.workflow_spec["steps"] if s["type"].startswith("ai.")),
                "credentials": compiled.credentials
            }
        )

    # Create new flow
    flow = FlowTable(
        name=compiled.flow_name,
        description=compiled.flow_description,
        definition={
            "dsl": compiled.raw_dsl,
            "workflow_spec": compiled.workflow_spec,
            "form_schema": compiled.form_schema,
            "policies": compiled.policies,
            "triggers": compiled.triggers,
            "credentials": compiled.credentials
        }
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)

    return RegisterFlowResponse(
        flow_id=str(flow.flow_id),
        name=compiled.flow_name,
        form_schema=compiled.form_schema,
        workflow_summary={
            "steps_count": len(compiled.workflow_spec["steps"]),
            "ai_steps": sum(1 for s in compiled.workflow_spec["steps"] if s["type"].startswith("ai.")),
            "credentials": compiled.credentials
        }
    )


def get_flow_graph_endpoint(flow_id: str, db: Session):
    """GET /flows/{flow_id}/graph - Get workflow graph."""
    flow_uuid = UUID(flow_id)
    flow = db.query(FlowTable).filter(FlowTable.flow_id == flow_uuid).first()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    workflow_spec = flow.definition.get("workflow_spec", {})
    steps = workflow_spec.get("steps", [])

    nodes = []
    edges = []

    # Build nodes
    for idx, step in enumerate(steps):
        step_id = step.get("id", f"step_{idx}")
        step_type = step.get("type", "unknown")

        nodes.append({
            "id": step_id,
            "label": step.get("description", step_id),
            "type": step_type
        })

    # Build edges (linear by default)
    for idx in range(len(steps) - 1):
        from_step = steps[idx].get("id", f"step_{idx}")
        to_step = steps[idx + 1].get("id", f"step_{idx + 1}")
        edges.append({
            "from": from_step,
            "to": to_step
        })

    # Add branch edges for ai.route steps
    for step in steps:
        if step.get("type") == "ai.route":
            step_id = step.get("id")
            branches = step.get("branches_enum", [])
            for branch in branches:
                edges.append({
                    "from": step_id,
                    "to": f"{step_id}_branch_{branch}",
                    "label": branch
                })

    return FlowGraphResponse(nodes=nodes, edges=edges)


def get_run_graph_endpoint(run_id: str, db: Session):
    """GET /runs/{run_id}/graph - Get run graph with status overlay."""
    run_uuid = UUID(run_id)
    run = db.query(RunTable).filter(RunTable.run_id == run_uuid).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Get base flow graph
    flow_graph_resp = get_flow_graph_endpoint(str(run.flow_id), db)

    # Build status map from run steps
    status_map = {}
    for step in run.steps:
        status_map[step.step_name] = step.status

    # Mark pending steps
    workflow_spec = run.flow.definition.get("workflow_spec", {})
    for step_def in workflow_spec.get("steps", []):
        step_id = step_def.get("id")
        if step_id not in status_map:
            status_map[step_id] = "pending"

    return RunGraphResponse(
        nodes=flow_graph_resp.nodes,
        edges=flow_graph_resp.edges,
        status=status_map
    )


def get_enhanced_run_endpoint(run_id: str, db: Session):
    """GET /runs/{run_id} - Enhanced with full step details and totals."""
    run_uuid = UUID(run_id)
    run = db.query(RunTable).filter(RunTable.run_id == run_uuid).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Build step details
    steps_detail = []
    artifacts_list = []

    for step in run.steps:
        duration_ms = None
        if step.completed_at and step.started_at:
            duration_ms = int((step.completed_at - step.started_at).total_seconds() * 1000)

        step_dict = {
            "id": step.step_name,
            "type": "unknown",  # Would need to look up from workflow_spec
            "status": step.status,
            "started_at": step.started_at.isoformat(),
            "completed_at": step.completed_at.isoformat() if step.completed_at else None,
            "duration_ms": duration_ms,
            "input": step.input_data,
            "output": step.output_data,
            "error": step.error,
            "tokens": step.tokens,
            "cost_usd": step.cost_usd
        }
        steps_detail.append(step_dict)

        # Collect artifacts
        if step.artifacts:
            artifacts_list.extend(step.artifacts)

    return EnhancedRunResponse(
        run_id=str(run.run_id),
        flow_id=str(run.flow_id),
        status=run.status.value,
        started_at=run.created_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        current_state=run.current_state,
        totals={
            "tokens": run.tokens_used,
            "cost_usd": run.cost_usd
        },
        steps=steps_detail,
        artifacts=list(set(artifacts_list))  # Deduplicate
    )
