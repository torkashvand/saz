"""Data Transfer Objects for read models."""

from dataclasses import dataclass
from datetime import datetime

from saz.domain.literals import PlannerMode, RunStatus, StepStatus


@dataclass
class FlowListItemDTO:
    """Flow list item DTO."""

    id: str
    name: str
    version: str | None
    description: str | None
    planner_mode: PlannerMode
    created_at: datetime


@dataclass
class FlowDetailDTO:
    """Flow detail DTO."""

    id: str
    name: str
    version: str | None
    description: str | None
    definition: dict
    source_yaml: str | None
    created_at: datetime


@dataclass
class RunListItemDTO:
    """Run list item DTO."""

    id: str
    flow_id: str
    status: RunStatus
    created_at: datetime
    completed_at: datetime | None
    cost_cents: int
    error: dict | None


@dataclass
class StepSummaryDTO:
    """Step summary DTO."""

    id: str
    number: int
    name: str
    attempt: int
    status: StepStatus
    start_ts: datetime | None
    end_ts: datetime | None
    duration_ms: int | None
    retry_count: int
    output: dict | None
    error: dict | None

    # Agentic loop tracking fields
    input: dict | None
    tokens: int | None
    cost_usd: float | None
    critique: dict | None
    policy_flags: dict | None
    step_type: str | None


@dataclass
class RunDetailDTO:
    """Run detail DTO with steps."""

    id: str
    flow_id: str
    flow_name: str
    status: RunStatus
    payload: dict
    error: dict | None
    cost_cents: int
    created_at: datetime
    completed_at: datetime | None
    steps: list[StepSummaryDTO]
    artifact_count: int


@dataclass
class CredentialListItemDTO:
    """Credential list item DTO (no secrets)."""

    name: str
    type: str
    description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class ArtifactDTO:
    """Artifact DTO."""

    id: str
    run_id: str
    step_id: str | None
    name: str
    blob_ref: str
    meta: dict
    created_at: datetime
