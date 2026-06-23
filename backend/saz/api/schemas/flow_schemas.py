"""Pydantic schemas for flow-related API endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from saz.domain.literals import PlannerMode
from saz.linter import LintFinding


class RegisterFlowRequest(BaseModel):
    """Request to register a new flow from YAML."""

    yaml: str = Field(..., description="Flow definition in YAML format")


class FlowLintRequest(BaseModel):
    """Request to lint a flow YAML without persisting."""

    yaml: str = Field(..., description="Flow YAML to lint")


class FlowLintResponse(BaseModel):
    """Consistency lint result. ``valid`` is False when any finding blocks."""

    valid: bool
    findings: list[LintFinding] = []
    llm_ran: bool = False
    compile_error: str | None = None


class RegisterFlowResponse(BaseModel):
    """Response after registering a flow."""

    id: str
    name: str
    version: str | None = None


class CompileFlowRequest(BaseModel):
    """Request to compile and validate a flow YAML."""

    yaml: str = Field(..., description="Flow YAML to compile and validate")


class WorkflowSummary(BaseModel):
    """Summary of workflow structure."""

    steps_count: int
    ai_steps: int
    credentials: list[str]


class CompileError(BaseModel):
    """Machine-readable validation error from the DSL compiler.

    Carries enough context for the Guided Builder to map an error back to
    the section / step that produced it.
    """

    code: str = Field(..., description="Stable error code (e.g. `step.missing_field`).")
    message: str = Field(..., description="Human-readable message.")
    section: str | None = Field(
        default=None, description="Top-level section (flow/form/workflow/...)"
    )
    step_id: str | None = Field(default=None, description="Step id when the error is per-step.")
    json_pointer: str | None = Field(
        default=None,
        description="RFC 6901 JSON pointer into the DSL document.",
    )


class CompileFlowResponse(BaseModel):
    """Response with compiled flow definition."""

    valid: bool = True
    flow_name: str
    flow_version: str | None = None
    flow_description: str | None = None
    form_schema: dict[str, Any]
    workflow_summary: WorkflowSummary
    warnings: list[str] = Field(default_factory=list)
    errors: list[CompileError] = Field(
        default_factory=list,
        description="Structured validation errors when valid=False.",
    )
    normalized_dsl: dict[str, Any] | None = Field(
        default=None,
        description=(
            "The normalized DSL the compiler produced. Frontend uses this to "
            "build the guided draft from canonical data when available."
        ),
    )


class UpdateFlowRequest(BaseModel):
    """Update an existing flow by ID. Differs from register in that the
    flow row is identified by `flow_id`, not by the flow's name — that
    lets users safely rename flows without creating a new row."""

    yaml: str = Field(..., description="Updated flow definition in YAML format.")


class WorkflowPolicies(BaseModel):
    """Workflow execution policies."""

    max_steps: int
    max_cost_usd: float
    max_tokens: int


class FlowDetail(BaseModel):
    """Detailed flow information."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    version: str | None = None
    description: str | None = None
    definition: dict[str, Any]
    original_yaml: str | None = None
    planner_mode: PlannerMode
    policies: WorkflowPolicies
    step_count: int
    created_at: datetime


class FlowListItem(BaseModel):
    """Flow list item."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    version: str | None = None
    description: str | None = None
    created_at: datetime


class FlowListResponse(BaseModel):
    """Response for listing flows."""

    items: list[FlowListItem]
    total: int


class FlowGraphResponse(BaseModel):
    """Response containing flow execution graph."""

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
