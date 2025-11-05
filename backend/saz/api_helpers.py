"""Pure helper functions extracted from API endpoints for testability.

These functions contain no side effects and are easily unit testable.
"""
from typing import Dict, List, Any


def build_flow_graph(workflow_spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build graph visualization data from workflow specification.

    Args:
        workflow_spec: Workflow specification with steps

    Returns:
        Dict with "nodes" and "edges" lists
    """
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

    return {"nodes": nodes, "edges": edges}


def build_run_status_map(run_steps: List[Any], workflow_spec: Dict[str, Any]) -> Dict[str, str]:
    """
    Build status map for run graph overlay.

    Args:
        run_steps: List of RunStepTable instances
        workflow_spec: Workflow specification with step definitions

    Returns:
        Dict mapping step_id to status string
    """
    status_map = {}

    # Add actual step statuses
    for step in run_steps:
        status_map[step.step_name] = step.status

    # Mark pending steps
    for step_def in workflow_spec.get("steps", []):
        step_id = step_def.get("id")
        if step_id and step_id not in status_map:
            status_map[step_id] = "pending"

    return status_map


def validate_form_payload(payload: Dict[str, Any], form_schema: Dict[str, Any]) -> tuple[bool, str | None]:
    """
    Validate payload against form schema.

    Args:
        payload: User-provided payload
        form_schema: JSON Schema for form

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Simple validation: check required fields exist
    required_fields = form_schema.get("required", [])
    for field in required_fields:
        if field not in payload:
            return False, f"Missing required field: {field}"

    return True, None


def extract_step_details(run_steps: List[Any]) -> tuple[List[Dict], List[str], int, float]:
    """
    Extract step details, artifacts, and totals from run steps.

    Args:
        run_steps: List of RunStepTable instances

    Returns:
        Tuple of (steps_detail, artifacts_list, total_tokens, total_cost)
    """
    steps_detail = []
    artifacts_list = []
    total_tokens = 0
    total_cost = 0.0

    for step in run_steps:
        duration_ms = None
        if step.completed_at and step.started_at:
            duration_ms = int((step.completed_at - step.started_at).total_seconds() * 1000)

        # Extract tokens/cost from step
        step_tokens = step.tokens or 0
        step_cost = step.cost_usd or 0.0
        total_tokens += step_tokens
        total_cost += step_cost

        step_dict = {
            "id": step.step_name,
            "type": step.input_data.get("type", "unknown") if step.input_data else "unknown",
            "status": step.status,
            "started_at": step.started_at.isoformat(),
            "completed_at": step.completed_at.isoformat() if step.completed_at else None,
            "duration_ms": duration_ms,
            "input": step.input_data,
            "output": step.output_data,
            "error": step.error,
            "tokens": step_tokens,
            "cost_usd": step_cost
        }
        steps_detail.append(step_dict)

        # Collect artifacts
        if step.artifacts:
            artifacts_list.extend(step.artifacts)

    return steps_detail, artifacts_list, total_tokens, total_cost
