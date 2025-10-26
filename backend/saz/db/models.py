"""Minimal database models (no Product/Subscription domain concepts)."""
from datetime import datetime, UTC
from uuid import uuid4
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Enum as SQLEnum, JSON, Integer, LargeBinary
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()


class ProcessStatusEnum(str, enum.Enum):
    CREATED = "created"
    RUNNING = "running"
    SUSPENDED = "suspended"
    WAITING = "waiting"
    FAILED = "failed"
    COMPLETED = "completed"


class CredentialTable(Base):
    """Encrypted credentials storage."""

    __tablename__ = "credentials"

    credential_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    # Encrypted JSON blob containing credential data
    encrypted_data = Column(LargeBinary, nullable=False)
    credential_type = Column(String(50), nullable=False)  # ssh_key, api_token, password, etc.
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class FlowTable(Base):
    """Registered form/workflow definitions."""

    __tablename__ = "flows"

    flow_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    # Stored as JSON: {form: {}, workflow: {}, json_schema: {}, budget: {}, triggers: {}, policies: {}, credentials: []}
    definition = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    runs = relationship("RunTable", back_populates="flow", cascade="all, delete-orphan")


class RunTable(Base):
    """Workflow run instances."""

    __tablename__ = "runs"

    run_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    flow_id = Column(UUID(as_uuid=True), ForeignKey("flows.flow_id"), nullable=False)
    status = Column(SQLEnum(ProcessStatusEnum), nullable=False, default=ProcessStatusEnum.CREATED)
    current_state = Column(JSON, nullable=False, default=dict)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    flow = relationship("FlowTable", back_populates="runs")
    steps = relationship("RunStepTable", back_populates="run", cascade="all, delete-orphan", order_by="RunStepTable.step_number")


class RunStepTable(Base):
    """Individual step executions within a run."""

    __tablename__ = "run_steps"

    step_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("runs.run_id"), nullable=False)
    step_number = Column(Integer, nullable=False)
    step_name = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False)
    input_data = Column(JSON, nullable=True)  # Step input (redacted)
    output_data = Column(JSON, nullable=True)  # Step output (redacted)
    error = Column(Text, nullable=True)  # Error message if failed
    retry_count = Column(Integer, nullable=False, default=0)  # Number of retry attempts
    artifacts = Column(JSON, nullable=True)  # List of artifact IDs produced by this step
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    run = relationship("RunTable", back_populates="steps")
