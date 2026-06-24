"""SQLAlchemy 2.0 ORM models."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from saz.domain.literals import Role


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class User(Base):
    """User aggregate - a person who can authenticate to Saz.

    Authorization is a single tier on ``role`` (admin / operator / viewer):

    * ``is_active`` — can the user log in (gate at authentication).
    * ``role``      — the authorization tier; ``admin`` reaches the admin
      user-management surface, ``viewer`` is read-only.

    ``must_change_password`` is set when an admin resets another user's
    password and cleared the next time that user successfully changes
    their own. The backend uses this flag to block all operational
    endpoints for the affected user until they have picked a new
    password — frontend redirection alone is not enough.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=Role.OPERATOR, index=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        flags = [self.role]
        if not self.is_active:
            flags.append("disabled")
        if self.must_change_password:
            flags.append("pw_change_required")
        suffix = f" [{','.join(flags)}]" if flags else ""
        return f"<User {self.username}{suffix}>"


class AuthSession(Base):
    """Server-side refresh session — the unit of revocation.

    The opaque refresh secret is never stored; only its hash. Access tokens
    carry this row's ``id`` in their ``sid`` claim, so revoking the session
    (logout, admin disable, password reset, refresh-replay) rejects the
    access token on its next request — well before its own ``exp``.

    Refresh rotates the secret on every use; the prior hash is retained for
    one generation so a replayed (already-rotated) secret is detected as
    theft and revokes the whole session.
    """

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    refresh_secret_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    previous_refresh_secret_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # How the session was established: "local" password login or "oidc" SSO.
    auth_method: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    provider_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    def is_active(self, now: datetime) -> bool:
        """A session is usable only while unrevoked and within both timeouts.

        Normalises naive timestamps to UTC: SQLite (dev/tests) drops tzinfo on
        read while Postgres (prod) preserves it, so compare defensively.
        """

        def _aware(value: datetime) -> datetime:
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

        return (
            self.revoked_at is None
            and now < _aware(self.idle_expires_at)
            and now < _aware(self.absolute_expires_at)
        )


class AuthProvider(Base):
    """An OIDC SSO provider configuration, managed by admins.

    The client secret is stored Fernet-encrypted and never returned by the
    API. Endpoints are resolved from the issuer's discovery document at login
    time, so only the ``issuer`` URL is stored, not individual endpoints.
    """

    __tablename__ = "auth_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    client_id: Mapped[str] = mapped_column(String(512), nullable=False)
    # Null for public (PKCE-only) clients that authenticate without a secret.
    client_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    scopes: Mapped[str] = mapped_column(String(512), nullable=False, default="openid profile email")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Comma-separated email domain allowlist; empty/None means no restriction.
    allowed_domains: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Auto-create a local user on first login when the IdP email is verified.
    jit_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Role granted to JIT-provisioned users (default: read-only viewer).
    default_role: Mapped[str] = mapped_column(String(20), nullable=False, default=Role.VIEWER)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class ExternalIdentity(Base):
    """A link between a local user and an external IdP subject.

    Identity is keyed by ``(issuer, subject)`` — stable across email changes.
    Email is retained only as a linking hint and for display.
    """

    __tablename__ = "external_identities"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_external_identity_subject"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Flow(Base):
    """Flow aggregate - workflow definition."""

    __tablename__ = "flows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_yaml: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # Relationship
    runs: Mapped[list["Run"]] = relationship(
        "Run", back_populates="flow", cascade="all, delete-orphan"
    )


class Run(Base):
    """Run aggregate - workflow execution instance."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    flow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("flows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    # queued, running, suspended, failed, completed
    planner_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="deterministic")
    # deterministic, agentic
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cost_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Compliance tracking fields
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    policy_violations: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # UX enhancement fields
    error_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    run_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    triggered_by: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # Relationships
    flow: Mapped["Flow"] = relationship("Flow", back_populates="runs")
    steps: Mapped[list["Step"]] = relationship(
        "Step",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="[Step.number, Step.attempt]",
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        "Artifact", back_populates="run", cascade="all, delete-orphan"
    )
    events: Mapped[list["Event"]] = relationship(
        "Event", back_populates="run", cascade="all, delete-orphan", order_by="Event.timestamp"
    )


class Step(Base):
    """Step entity - individual execution step within a run."""

    __tablename__ = "steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    # queued, running, suspended, failed, completed
    start_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Agentic loop tracking fields
    input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)
    critique: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    policy_flags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    step_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Relationships
    run: Mapped["Run"] = relationship("Run", back_populates="steps")
    artifacts: Mapped[list["Artifact"]] = relationship(
        "Artifact", back_populates="step", cascade="all, delete-orphan"
    )
    events: Mapped[list["Event"]] = relationship(
        "Event", back_populates="step", cascade="all, delete-orphan", order_by="Event.timestamp"
    )

    def __repr__(self) -> str:
        return f"<Step {self.number}:{self.name} attempt={self.attempt} status={self.status}>"


class Artifact(Base):
    """Artifact entity - generated outputs from steps."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("steps.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    blob_ref: Mapped[str] = mapped_column(String(1000), nullable=False)  # file path or storage ref
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    run: Mapped["Run"] = relationship("Run", back_populates="artifacts")
    step: Mapped["Step"] = relationship("Step", back_populates="artifacts")


class Credential(Base):
    """Credential aggregate - encrypted secrets."""

    __tablename__ = "credentials"

    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # api_token, ssh_key, password, etc.
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    data_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class Event(Base):
    """Event entity - immutable audit event log."""

    __tablename__ = "events"

    # Primary identity
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Monotonic per-run sequence for deterministic ordering of the event
    # stream. Nullable for rows written before this column existed.
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Context (foreign keys for joins)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("steps.id", ondelete="CASCADE"), nullable=True, index=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # Metadata
    planner_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="info")
    actor: Mapped[str] = mapped_column(String(10), nullable=False, default="system")
    # NULL when actor in {"system", "llm"} — those events have no human owner
    # by definition. Set only when actor == "user".
    actor_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Content
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    tags: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Relationships
    run: Mapped["Run"] = relationship("Run", back_populates="events")
    step: Mapped["Step | None"] = relationship("Step", back_populates="events")

    def __repr__(self) -> str:
        return f"<Event {self.event_type} @ {self.timestamp}>"
