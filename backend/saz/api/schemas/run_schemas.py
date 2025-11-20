"""Pydantic schemas for run-related API endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CreateRunRequest(BaseModel):
    """Request to create a new run."""

    flow_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CreateRunResponse(BaseModel):
    """Response after creating a run."""

    id: str
    flow_id: str
    status: str


class RunListItem(BaseModel):
    """Run list item with summary information."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    flow_id: str
    flow_name: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    total_cost_usd: float
    total_tokens: int
    error: dict[str, Any] | None = None


class RunListResponse(BaseModel):
    """Response for listing runs."""

    items: list[RunListItem]
    total: int
    limit: int
    offset: int


class RunSummary(BaseModel):
    """Run summary with basic information (no steps)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    flow_id: str
    flow_name: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    total_cost_usd: float
    total_tokens: int
    step_count: int
    error: dict[str, Any] | None = None


class StepSummary(BaseModel):
    """Summary of a single step in a run."""

    id: str
    number: int
    name: str
    step_type: str | None = None
    status: str
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    duration_ms: int | None = None
    retry_count: int = 0
    tokens: int | None = None
    cost_usd: float | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class RunDetail(BaseModel):
    """Detailed run information with all fields."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    flow_id: str
    flow_name: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    total_cost_usd: float
    total_tokens: int
    input_data: dict[str, Any] | None = None
    output_data: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    steps: list[Any] = Field(default_factory=list)  # Can be StepSummary or db model


class RunDetailResponse(BaseModel):
    """Detailed run information with steps."""

    id: str
    flow_id: str
    flow_name: str
    status: str
    planner_mode: str
    payload: dict[str, Any]
    error: dict[str, Any] | None = None
    created_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    total_tokens: int
    total_cost_usd: float
    policy_violations: dict[str, Any] | None = None
    steps: list[StepSummary]


class RunStepsResponse(BaseModel):
    """Response containing run steps."""

    run_id: str
    status: str
    steps: list[StepSummary]


class RunGraphResponse(BaseModel):
    """Response containing run execution graph."""

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionGraphResponse(BaseModel):
    """Response containing execution graph for a specific run."""

    run_id: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class RetryRunRequest(BaseModel):
    """Request to retry a failed run."""

    override_input: dict[str, Any] | None = Field(None, description="Optional input overrides")


class RetryRunResponse(BaseModel):
    """Response after retrying a run."""

    new_run_id: str
    original_run_id: str
    status: str


class ReplayRunRequest(BaseModel):
    """Request to replay a run with optional input modifications."""

    override_input: dict[str, Any] | None = Field(None, description="Optional input overrides")


class ReplayRunResponse(BaseModel):
    """Response after replaying a run."""

    new_run_id: str
    original_run_id: str
    status: str


class ComplianceReport(BaseModel):
    """Compliance and audit report for a run."""

    run_id: str
    flow_id: str
    status: str
    total_tokens: int
    total_cost_usd: float
    duration_ms: int | None = None
    policy_violations: dict[str, Any] | None = None
    steps_analyzed: int
    compliance_score: float  # 0.0 - 1.0
    findings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ComplianceReportResponse(BaseModel):
    """Response containing compliance report for a run."""

    run_id: str
    report: dict[str, Any]
