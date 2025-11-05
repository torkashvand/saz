"""SQLAlchemy 2.0 ORM models."""
from datetime import datetime, UTC
from uuid import uuid4
from typing import Optional
from sqlalchemy import String, Integer, LargeBinary, JSON, ForeignKey, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class Flow(Base):
    """Flow aggregate - workflow definition."""
    __tablename__ = "flows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), nullable=False)

    # Relationship
    runs: Mapped[list["Run"]] = relationship("Run", back_populates="flow", cascade="all, delete-orphan")


class Run(Base):
    """Run aggregate - workflow execution instance."""
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    flow_id: Mapped[str] = mapped_column(String(36), ForeignKey("flows.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    # queued, running, suspended, failed, completed
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    cost_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), nullable=False, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Relationships
    flow: Mapped["Flow"] = relationship("Flow", back_populates="runs")
    steps: Mapped[list["Step"]] = relationship("Step", back_populates="run", cascade="all, delete-orphan", order_by="Step.number")
    artifacts: Mapped[list["Artifact"]] = relationship("Artifact", back_populates="run", cascade="all, delete-orphan")


class Step(Base):
    """Step entity - individual execution step within a run."""
    __tablename__ = "steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    # queued, running, suspended, failed, completed
    start_ts: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    end_ts: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    run: Mapped["Run"] = relationship("Run", back_populates="steps")
    artifacts: Mapped[list["Artifact"]] = relationship("Artifact", back_populates="step", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Step {self.number}:{self.name} status={self.status}>"


class Artifact(Base):
    """Artifact entity - generated outputs from steps."""
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    step_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("steps.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    blob_ref: Mapped[str] = mapped_column(String(1000), nullable=False)  # file path or storage ref
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), nullable=False)

    # Relationships
    run: Mapped["Run"] = relationship("Run", back_populates="artifacts")
    step: Mapped[Optional["Step"]] = relationship("Step", back_populates="artifacts")


class Credential(Base):
    """Credential aggregate - encrypted secrets."""
    __tablename__ = "credentials"

    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # api_token, ssh_key, password, etc.
    description: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    data_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False)