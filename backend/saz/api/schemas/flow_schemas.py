"""Pydantic schemas for flow-related API endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from saz.domain.literals import PlannerMode


class RegisterFlowRequest(BaseModel):
    """Request to register a new flow from YAML."""

    yaml: str = Field(..., description="Flow definition in YAML format")


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


class CompileFlowResponse(BaseModel):
    """Response with compiled flow definition."""

    flow_name: str
    flow_version: str | None = None
    flow_description: str | None = None
    form_schema: dict[str, Any]
    workflow_summary: WorkflowSummary
    warnings: list[str] = Field(default_factory=list)


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
