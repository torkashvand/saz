"""Base repository classes."""
from typing import Generic, TypeVar, Type, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select


T = TypeVar('T')


class BaseRepository(Generic[T]):
    """Base repository with common CRUD operations."""

    def __init__(self, session: Session, model: Type[T]):
        self.session = session
        self.model = model

    def get(self, id: str) -> Optional[T]:
        """Get entity by ID."""
        stmt = select(self.model).where(self.model.id == id)
        return self.session.scalar(stmt)

    def add(self, entity: T) -> T:
        """Add new entity to session."""
        self.session.add(entity)
        return entity

    def delete(self, entity: T) -> None:
        """Delete entity from session."""
        self.session.delete(entity)