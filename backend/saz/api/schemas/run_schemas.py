"""Pydantic schemas for run-related API endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from saz.domain.literals import PlannerMode, RunStatus, StepStatus


class CreateRunRequest(BaseModel):
    """Request to create a new run."""

    flow_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CreateRunResponse(BaseModel):
    """Response after creating a run."""

    id: str
    flow_id: str
    status: RunStatus


class RunListItem(BaseModel):
    """Run list item with summary information."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    flow_id: str
    flow_name: str
    status: RunStatus
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
    status: RunStatus
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
    attempt: int = 1
    step_type: str
    status: StepStatus
    start_ts: datetime | None = None  # ISO string in response
    end_ts: datetime | None = None  # ISO string in response
    duration_ms: int | None = None
    retry_count: int = 0
    tokens: int | None = None
    cost_usd: float | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    description: str | None = Field(default=None, description="User-friendly step description")
    failure_reason: str | None = Field(default=None, description="Human-readable failure message")
    error_category: str | None = Field(default=None, description="Categorized error type")


class RunDetail(BaseModel):
    """Detailed run information with all fields."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    flow_id: str
    flow_name: str
    status: RunStatus
    created_at: datetime
    completed_at: datetime | None = None
    total_cost_usd: float
    total_tokens: int
    input_data: dict[str, Any] | None = None
    output_data: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    steps: list[Any] = Field(default_factory=list)  # Can be StepSummary or db model


class ErrorSummarySchema(BaseModel):
    """Human-readable error summary with remediation actions."""

    message: str = Field(..., description="Human-readable error message")
    category: str = Field(..., description="Error category (missing_credential, http_error, etc.)")
    failed_step_number: int | None = Field(None, description="Step number where error occurred")
    failed_step_name: str | None = Field(None, description="Step name where error occurred")
    remediation_actions: list[str] = Field(
        default_factory=list, description="Suggested remediation actions"
    )
    technical_details: dict[str, Any] = Field(
        default_factory=dict,
        description="Technical details (error_type, stack_trace, raw_error, etc.)",
    )


class RunMetadataSchema(BaseModel):
    """Aggregated metadata for a run."""

    total_steps: int
    succeeded_steps: int
    failed_steps: int
    running_steps: int
    skipped_steps: int


class TriggeredBySchema(BaseModel):
    """Run attribution: who or what initiated the run."""

    type: str = Field(..., description="Originator: 'user' or 'system'.")
    user_id: str | None = None
    user_name: str | None = None


class PlannedStepSchema(BaseModel):
    """Planned step from workflow definition (before execution)."""

    index: int = Field(..., description="0-based step index in planned sequence")
    id: str = Field(..., description="Step identifier from workflow definition")
    name: str = Field(..., description="Human-readable step name/label")
    step_type: str | None = Field(None, description="Step type (tool.call, ai.extract, etc.)")


class RunDetailResponse(BaseModel):
    """Detailed run information with steps."""

    id: str
    flow_id: str
    flow_name: str
    status: RunStatus
    planner_mode: PlannerMode
    payload: dict[str, Any]
    error: dict[str, Any] | None = None
    created_at: datetime
    completed_at: datetime | None = None
    started_at: datetime | None = Field(None, description="When run actually started execution")
    duration_ms: int | None = None
    total_tokens: int
    total_cost_usd: float
    policy_violations: dict[str, Any] | None = None
    steps: list[StepSummary]

    error_summary: ErrorSummarySchema | None = Field(
        None, description="Human-readable error summary"
    )
    run_metadata: RunMetadataSchema | None = Field(None, description="Aggregated step counts")
    triggered_by: TriggeredBySchema | None = Field(None, description="Who/what triggered this run")
    planned_steps: list[PlannedStepSchema] = Field(
        default_factory=list,
        description="Planned steps from workflow definition (for deterministic flows)",
    )


class RunStepsResponse(BaseModel):
    """Response containing run steps."""

    run_id: str
    status: RunStatus
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
    """Response after retrying a run (same-run semantics)."""

    run_id: str
    status: RunStatus


class ComplianceReport(BaseModel):
    """Compliance and audit report for a run."""

    run_id: str
    flow_id: str
    status: RunStatus
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
