"""Unit of Work pattern implementation."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from saz.domain.event_schema import Event as EventSchema
from saz.repositories.read.event_queries import EventQueries
from saz.repositories.read.flow_read_repository import FlowReadRepository
from saz.repositories.read.run_read_repository import RunReadRepository
from saz.repositories.write.artifact_repository import ArtifactRepository
from saz.repositories.write.auth_provider_repository import (
    AuthProviderRepository,
    ExternalIdentityRepository,
)
from saz.repositories.write.auth_session_repository import AuthSessionRepository
from saz.repositories.write.credential_repository import CredentialRepository
from saz.repositories.write.event_repository import EventRepository
from saz.repositories.write.flow_repository import FlowRepository
from saz.repositories.write.run_repository import RunRepository
from saz.repositories.write.step_repository import StepRepository
from saz.repositories.write.user_repository import UserRepository


class UnitOfWork:
    """Unit of Work manages session lifecycle and repositories."""

    def __init__(self, session: Session):
        self._session = session
        self._event_buffer: list[EventSchema] = []  # Unified event buffer

        # Write repositories
        self.runs: RunRepository | None = None
        self.steps: StepRepository | None = None
        self.flows: FlowRepository | None = None
        self.credentials: CredentialRepository | None = None
        self.artifacts: ArtifactRepository | None = None
        self.events_repo: EventRepository | None = None
        self.users: UserRepository | None = None
        self.auth_sessions: AuthSessionRepository | None = None
        self.auth_providers: AuthProviderRepository | None = None
        self.external_identities: ExternalIdentityRepository | None = None

        # Read repositories
        self.run_reads: RunReadRepository | None = None
        self.flow_reads: FlowReadRepository | None = None
        self.event_queries: EventQueries | None = None

    def __enter__(self) -> "UnitOfWork":
        """Context manager entry - initialize repositories."""
        # Write repositories
        self.runs = RunRepository(self._session)
        self.steps = StepRepository(self._session)
        self.flows = FlowRepository(self._session)
        self.credentials = CredentialRepository(self._session)
        self.artifacts = ArtifactRepository(self._session)
        self.events_repo = EventRepository(self._session)
        self.users = UserRepository(self._session)
        self.auth_sessions = AuthSessionRepository(self._session)
        self.auth_providers = AuthProviderRepository(self._session)
        self.external_identities = ExternalIdentityRepository(self._session)

        # Read repositories
        self.run_reads = RunReadRepository(self._session)
        self.flow_reads = FlowReadRepository(self._session)
        self.event_queries = EventQueries(self._session)

        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - cleanup."""
        if exc_type is not None:
            self.rollback()
        # Don't close session - let the session owner handle that

    def commit(self) -> list[EventSchema]:
        """
        Commit transaction and persist buffered events.

        Returns:
            List of emitted events for broadcasting
        """
        # Batch insert events for performance
        if self._event_buffer and self.events_repo:
            self.events_repo.add_batch(self._event_buffer)

        self._session.commit()

        # Return emitted events for broadcasting
        emitted = self._event_buffer.copy()
        self._event_buffer.clear()
        return emitted

    def rollback(self) -> None:
        """Rollback transaction and clear event buffer."""
        self._session.rollback()
        self._event_buffer.clear()

    def emit_event(self, event: EventSchema) -> None:
        """
        Buffer an event to be persisted on commit.

        Args:
            event: Event to emit
        """
        self._event_buffer.append(event)

    @property
    def pending_events(self) -> list[EventSchema]:
        """Get pending events in buffer."""
        return self._event_buffer.copy()

    def execute(self, query: str) -> Any:
        return self._session.execute(text(query))
