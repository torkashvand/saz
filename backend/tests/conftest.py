"""Pytest configuration and shared fixtures for tests."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set test DATABASE_URL before importing saz modules (will be updated per test)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from saz.api import app
from saz.db.dependencies import get_uow
from saz.db.models import Base
from saz.db.unit_of_work import UnitOfWork
from saz.domain.events import DomainEvent


@pytest.fixture(scope="function")
def db_engine():
    """Create test database engine using temporary file."""
    import tempfile

    # Use a temporary file for each test to avoid threading issues
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        db_path = tmp_file.name

    try:
        database_url = f"sqlite:///{db_path}"
        engine = create_engine(database_url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        yield engine
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
    finally:
        # Clean up the temporary file
        if os.path.exists(db_path):
            os.unlink(db_path)


@pytest.fixture(scope="function")
def event_collector():
    """Collect broadcasted events for assertions."""
    events = []

    async def capture_events(event_list: list[DomainEvent]):
        """Capture events instead of broadcasting."""
        events.extend(event_list)

    with patch("saz.api.websocket.broadcast_events", side_effect=capture_events):
        yield events


@pytest.fixture(scope="function")
def sync_executor(db_engine):
    """Override scheduler to use synchronous execution for tests."""
    from saz.engine.scheduler import RunScheduler, _scheduler_lock

    # Get the database URL from the engine
    database_url = str(db_engine.url)

    # Create a single-thread executor for deterministic testing
    class SyncScheduler(RunScheduler):
        def __init__(self, database_url: str):
            # Skip parent init to avoid double init
            if hasattr(self, "_initialized"):
                return
            self._initialized = True

            self.database_url = database_url
            self.max_workers = 1
            # Single thread executor for deterministic testing
            self.executor = ThreadPoolExecutor(max_workers=1)
            self.engine = db_engine
            self.SessionLocal = sessionmaker(bind=self.engine)
            self._running_runs = set()
            import threading

            self._running_lock = threading.Lock()

    # Patch the scheduler module
    with _scheduler_lock:
        import saz.engine.scheduler as sched_module

        original_scheduler = sched_module._scheduler
        sched_module._scheduler = SyncScheduler(database_url)

        yield sched_module._scheduler

        # Cleanup
        if sched_module._scheduler:
            try:
                sched_module._scheduler.shutdown(wait=True)
            except Exception:
                pass
        sched_module._scheduler = original_scheduler


@pytest.fixture(scope="function")
def app_client(db_engine, sync_executor, event_collector):
    """Create FastAPI test client with UnitOfWork override."""
    # Create a session factory bound to the test engine
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def override_get_uow():
        # Create a NEW session for each request (like production)
        session = TestingSessionLocal()
        try:
            with UnitOfWork(session) as uow:
                yield uow
        finally:
            session.close()

    app.dependency_overrides[get_uow] = override_get_uow

    # Use TestClient with raise_server_exceptions to catch executor errors
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def frozen_time():
    """Freeze time for deterministic timestamps."""
    fixed_time = datetime(2025, 1, 1, 12, 0, 0)

    with patch("saz.engine.executor.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = fixed_time
        mock_datetime.now.return_value = fixed_time
        yield fixed_time
