"""Dependency injection for FastAPI."""

from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from saz.db.session import get_session
from saz.db.unit_of_work import UnitOfWork


def get_uow(session: Session = Depends(get_session)) -> Generator[UnitOfWork, None, None]:
    """Get Unit of Work (dependency injection)."""
    with UnitOfWork(session) as uow:
        yield uow
