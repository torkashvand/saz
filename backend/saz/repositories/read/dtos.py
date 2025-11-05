"""Data Transfer Objects for read models."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class FlowListItemDTO:
    """Flow list item DTO."""
    id: str
    name: str
    version: Optional[str]
    description: Optional[str]
    created_at: datetime


@dataclass
class FlowDetailDTO:
    """Flow detail DTO."""
    id: str
    name: str
    version: Optional[str]
    description: Optional[str]
    definition: dict
    created_at: datetime


@dataclass
class RunListItemDTO:
    """Run list item DTO."""
    id: str
    flow_id: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime]
    cost_cents: int


@dataclass
class StepSummaryDTO:
    """Step summary DTO."""
    id: str
    number: int
    name: str
    status: str
    start_ts: Optional[datetime]
    end_ts: Optional[datetime]
    duration_ms: Optional[int]
    retry_count: int
    error: Optional[dict]


@dataclass
class RunDetailDTO:
    """Run detail DTO with steps."""
    id: str
    flow_id: str
    flow_name: str
    status: str
    payload: dict
    error: Optional[dict]
    cost_cents: int
    created_at: datetime
    completed_at: Optional[datetime]
    steps: list[StepSummaryDTO]
    artifact_count: int


@dataclass
class CredentialListItemDTO:
    """Credential list item DTO (no secrets)."""
    name: str
    type: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass
class ArtifactDTO:
    """Artifact DTO."""
    id: str
    run_id: str
    step_id: Optional[str]
    name: str
    blob_ref: str
    meta: dict
    created_at: datetime