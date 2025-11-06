"""Base repository classes."""

from typing import Any, Protocol, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session


class HasId(Protocol):
    """Protocol for entities with an id attribute."""

    id: Any


T = TypeVar('T', bound=HasId)


class BaseRepository[T]:
    """Base repository with common CRUD operations."""

    def __init__(self, session: Session, model: type[T]):
        self.session = session
        self.model = model

    def get(self, id: str) -> T | None:
        """Get entity by ID."""
        stmt = select(self.model).where(self.model.id == id)  # type: ignore[attr-defined]
        return self.session.scalar(stmt)

    def add(self, entity: T) -> T:
        """Add new entity to session."""
        self.session.add(entity)
        return entity

    def delete(self, entity: T) -> None:
        """Delete entity from session."""
        self.session.delete(entity)
