"""Pytest configuration and shared fixtures for tests."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set environment variables BEFORE importing any saz module so the settings
# singleton picks them up on first instantiation.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
# Disable the SuspensionSweeper background thread for tests — each test gets
# its own temp-file SQLite engine, so a process-wide sweeper running against
# a stale DATABASE_URL would error on "no such table: runs". Tests that need
# the sweeper drive it synchronously via SuspensionSweeper(engine=...).sweep_once().
os.environ["SUSPENSION_SWEEP_ENABLED"] = "False"
# Auth tests need a JWT secret. Set it before importing saz modules so the
# settings singleton picks it up.
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-do-not-use-in-prod")

from saz.agents import LLMPort, LLMResponse
from saz.api.app import app
from saz.api.dependencies import get_current_user
from saz.db.dependencies import get_uow
from saz.db.models import Base, User
from saz.db.unit_of_work import UnitOfWork
from saz.security import hash_password

# Fixed test-user id used everywhere a test inserts a Flow/Run/Credential
# directly. The `users` row is seeded into every fresh test database by the
# ``db_engine`` fixture so all FKs resolve without each test having to
# coordinate with the auth fixtures.
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_USER_USERNAME = "testuser"
TEST_USER_EMAIL = "testuser@example.com"
TEST_USER_PASSWORD = "test-password-123"


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

        # Seed the canonical test user so that direct ORM inserts of Flow,
        # Run, and Credential rows in legacy tests resolve their NOT NULL
        # ``created_by_user_id`` FK without each test having to manage the
        # auth fixture chain.
        seed_session = sessionmaker(bind=engine)()
        try:
            now = datetime.now(UTC)
            seed_session.add(
                User(
                    id=TEST_USER_ID,
                    username=TEST_USER_USERNAME,
                    email=TEST_USER_EMAIL,
                    display_name="Test User",
                    password_hash=hash_password(TEST_USER_PASSWORD),
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            seed_session.commit()
        finally:
            seed_session.close()

        yield engine
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
    finally:
        # Clean up the temporary file
        if os.path.exists(db_path):
            os.unlink(db_path)


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
def test_user_token(db_engine) -> str:
    """Mint a real JWT for the seeded test user.

    Use this in tests that exercise endpoints (like the WebSocket stream)
    that decode the token directly rather than going through the FastAPI
    ``get_current_user`` dependency override.
    """
    from saz.security import create_access_token

    token, _ = create_access_token(user_id=TEST_USER_ID, username=TEST_USER_USERNAME)
    return token


@pytest.fixture(scope="function")
def test_user(db_engine) -> User:
    """Return the seeded test user (created by ``db_engine``).

    Re-reads the row from a fresh session so callers get an ORM instance
    that's safe to use without binding lifetime concerns.
    """
    session = sessionmaker(bind=db_engine)()
    try:
        user = session.get(User, TEST_USER_ID)
        assert user is not None, "db_engine fixture failed to seed test user"
        session.expunge(user)
        return user
    finally:
        session.close()


@pytest.fixture(scope="function")
def app_client(db_engine, sync_executor, test_user):
    """FastAPI test client that auto-authenticates as ``test_user``.

    Existing tests treat the API as if no auth exists; rather than rewriting
    every test to log in, we override ``get_current_user`` to return the
    seeded user. Tests that specifically want to exercise the auth gate use
    ``unauthenticated_app_client`` instead.
    """
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def override_get_uow():
        session = TestingSessionLocal()
        try:
            with UnitOfWork(session) as uow:
                yield uow
        finally:
            session.close()

    def override_current_user() -> User:
        # Re-read the user from the test engine on each request so the
        # ORM-attached row belongs to a live session and SQLAlchemy will
        # not complain about a detached instance.
        session = TestingSessionLocal()
        try:
            user = session.get(User, test_user.id)
            assert user is not None
            session.expunge(user)
            return user
        finally:
            session.close()

    app.dependency_overrides[get_uow] = override_get_uow
    app.dependency_overrides[get_current_user] = override_current_user

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def unauthenticated_app_client(db_engine, sync_executor):
    """Test client with no current-user override — every protected endpoint
    will return 401. Use for negative tests that verify the auth gate."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def override_get_uow():
        session = TestingSessionLocal()
        try:
            with UnitOfWork(session) as uow:
                yield uow
        finally:
            session.close()

    app.dependency_overrides[get_uow] = override_get_uow

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


class MockLLMPort(LLMPort):
    """Mock LLM port for testing - returns fixed responses."""

    def __init__(self, responses: list[str] | None = None):
        """
        Initialize mock LLM port.

        Args:
            responses: List of response strings to return in sequence.
                      If None, returns default success response.
        """
        self.responses = responses or []
        self.call_count = 0
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> LLMResponse:
        """Return fixed response and track call."""
        # Record call details
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
            }
        )

        # Get response content
        if self.call_count < len(self.responses):
            content = self.responses[self.call_count]
        else:
            # Default success response based on format
            if response_format and response_format.get("type") == "json_object":
                content = json.dumps({"status": "success", "result": "mock"})
            else:
                content = "Mock LLM response"

        self.call_count += 1

        return LLMResponse(
            content=content, total_tokens=100, prompt_tokens=50, completion_tokens=50, model=model
        )


@pytest.fixture
def mock_llm_port():
    """Create mock LLM port."""
    return MockLLMPort()


@pytest.fixture
def mock_llm_with_plan(mock_llm_port):
    """Mock LLM port that returns a valid execution plan."""
    plan = {
        "plan_id": "12345678-1234-1234-1234-123456789abc",
        "steps": [
            {
                "step_id": "test_step",
                "step_type": "tool.call",
                "tool_name": "http_request",
                "input_template": {"url": "https://example.com"},
                "expected_output_schema": {"type": "object"},
                "error_handling": "retry",
                "max_retries": 3,
                "reasoning": "Test step",
            }
        ],
        "estimated_cost_usd": 0.001,
        "estimated_time_seconds": 5,
        "reasoning": "Test plan",
    }
    mock_llm_port.responses = [json.dumps(plan)]
    return mock_llm_port


@pytest.fixture
def mock_llm_with_critique(mock_llm_port):
    """Mock LLM port that returns a valid critique."""
    critique = {
        "verdict": "pass",
        "reasoning": "Step completed successfully",
        "issues": [],
        "safety_flags": [],
        "suggestions": {"next_action": "continue"},
        "confidence": 0.95,
    }
    mock_llm_port.responses = [json.dumps(critique)]
    return mock_llm_port
