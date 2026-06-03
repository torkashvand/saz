"""Controlled string types shared across the codebase.

These exist because several finite value sets — run status, step status,
planner mode, audit severity, audit actor — were previously typed as
plain ``str`` and documented only in comments. Each one drives real
workflow or audit behaviour and is referenced from multiple modules, so
they live here as :class:`enum.StrEnum`.

Why :class:`StrEnum` and not :data:`typing.Literal`:

* These value sets are reused by Pydantic schemas, the executor, the
  repository layer, and audit emitters. Centralising prevents the
  Literal unions from drifting.
* :class:`StrEnum` members **are** ``str`` instances, so existing
  comparisons (``if step.status == "completed"``) and DB columns typed
  ``Mapped[str]`` keep working without changes.
* Pydantic v2 emits the underlying string when serialising, so JSON
  payloads on the wire are still plain strings.

Small / local value sets (e.g. ``WebhookCallbackRequest.action``) use
:data:`typing.Literal` defined alongside the schema they belong to —
they don't earn a home here.
"""

from enum import StrEnum


class RunStatus(StrEnum):
    """Lifecycle of a workflow Run.

    Assigned in :mod:`saz.repositories.write.run_repository` and the
    executor; read by API schemas and the suspension sweeper. ``failed``
    is the single terminal-failure state — no production path writes
    ``"error"``.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUSPENDED = "suspended"
    FAILED = "failed"
    COMPLETED = "completed"


class StepStatus(StrEnum):
    """Lifecycle of a Step inside a Run.

    Mirrors :class:`RunStatus` today but kept as a separate type because
    the two concepts can diverge (e.g. a Step may be ``failed`` while
    the Run is still ``running`` in a retry scenario).
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUSPENDED = "suspended"
    FAILED = "failed"
    COMPLETED = "completed"
    # A step whose ``when`` guard evaluated false — never executed, no side
    # effects. Distinct from completed so the UI and downstream logic do not
    # treat a skipped step as a successful one.
    SKIPPED = "skipped"


class PlannerMode(StrEnum):
    """Which planner the run executes under.

    ``deterministic`` translates ``workflow.steps`` 1:1; ``agentic``
    uses an LLM planner to derive the execution plan from the DSL +
    tool catalogue.
    """

    DETERMINISTIC = "deterministic"
    AGENTIC = "agentic"


class Severity(StrEnum):
    """Audit-event severity. ``warn`` (not ``warning``) for column-width
    compatibility with the existing DB schema."""

    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class Actor(StrEnum):
    """Who initiated an audit event.

    ``system`` covers engine-driven transitions, ``user`` is for events
    attributable to an authenticated person (also stamps
    ``actor_user_id``), and ``llm`` covers planner/critic agents.
    """

    SYSTEM = "system"
    USER = "user"
    LLM = "llm"


__all__ = [
    "Actor",
    "PlannerMode",
    "RunStatus",
    "Severity",
    "StepStatus",
]
