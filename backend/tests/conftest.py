"""Pytest configuration and shared fixtures for tests."""
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set test DATABASE_URL before importing saz modules
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from saz.db.models import Base
from saz.db.dependencies import get_uow
from saz.db.unit_of_work import UnitOfWork
from saz.api import app


# Test database (in-memory SQLite)
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_engine():
    """Create test database engine."""
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Create test database session."""
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_engine
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def app_client(db_session):
    """Create FastAPI test client with UnitOfWork override."""
    def override_get_uow():
        try:
            yield UnitOfWork(db_session)
        finally:
            pass

    app.dependency_overrides[get_uow] = override_get_uow
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
