"""Unit of Work pattern implementation."""

from typing import Any

from sqlalchemy.orm import Session

from saz.domain.events import DomainEvent
from saz.repositories.read.flow_read_repository import FlowReadRepository
from saz.repositories.read.run_read_repository import RunReadRepository
from saz.repositories.write.artifact_repository import ArtifactRepository
from saz.repositories.write.credential_repository import CredentialRepository
from saz.repositories.write.flow_repository import FlowRepository
from saz.repositories.write.run_repository import RunRepository
from saz.repositories.write.step_repository import StepRepository


class UnitOfWork:
    """Unit of Work manages session lifecycle and repositories."""

    def __init__(self, session: Session):
        self._session = session
        self._events: list[DomainEvent] = []

        # Write repositories
        self.runs: RunRepository | None = None
        self.steps: StepRepository | None = None
        self.flows: FlowRepository | None = None
        self.credentials: CredentialRepository | None = None
        self.artifacts: ArtifactRepository | None = None

        # Read repositories
        self.run_reads: RunReadRepository | None = None
        self.flow_reads: FlowReadRepository | None = None

    def __enter__(self) -> "UnitOfWork":
        """Context manager entry - initialize repositories."""
        # Write repositories
        self.runs = RunRepository(self._session)
        self.steps = StepRepository(self._session)
        self.flows = FlowRepository(self._session)
        self.credentials = CredentialRepository(self._session)
        self.artifacts = ArtifactRepository(self._session)

        # Read repositories
        self.run_reads = RunReadRepository(self._session)
        self.flow_reads = FlowReadRepository(self._session)

        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - cleanup."""
        if exc_type is not None:
            self.rollback()
        # Don't close session - let the session owner handle that

    def commit(self) -> None:
        """Commit transaction."""
        self._session.commit()

    def rollback(self) -> None:
        """Rollback transaction."""
        self._session.rollback()

    def add_event(self, event: DomainEvent) -> None:
        """Add domain event to outbox."""
        self._events.append(event)

    def collect_events(self) -> list[DomainEvent]:
        """Collect and clear domain events."""
        events = self._events.copy()
        self._events.clear()
        return events

    @property
    def events(self) -> list[DomainEvent]:
        """Get current events."""
        return self._events.copy()
