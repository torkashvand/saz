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
# Disable the SuspensionSweeper background thread for tests; tests that need
# the sweeper drive it synchronously via SuspensionSweeper(engine=...).sweep_once().
os.environ["SUSPENSION_SWEEP_ENABLED"] = "False"
# Auth tests need a JWT secret. Set it before importing saz modules so the
# settings singleton picks it up.
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-do-not-use-in-prod")
# Credential tests encrypt/decrypt with Fernet, which rejects a blank key.
# Provide a valid throwaway key so the suite is self-contained and does not
# depend on a developer's local .env (CI sets no CREDENTIALS_ENCRYPTION_KEY).
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", "dd0qHBIV-Wv_KlnZVjRzzfl4x8crVfFargy4WRUV_FI=")

# --- PostgreSQL test database (one isolated database per xdist worker) ---
# Tests run against PostgreSQL only, for production parity: foreign-key
# enforcement, JSON, and real transaction semantics that SQLite did not give
# us. Point TEST_DATABASE_URL at a reachable cluster; each worker creates and
# tears down its own database, so parallel runs never collide.
from sqlalchemy.engine import make_url  # noqa: E402

_TEST_DB_BASE = make_url(
    os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg2://saz:saz@localhost:5433/saz_test")
)
_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "main")
_WORKER_DB = f"{_TEST_DB_BASE.database}_{_WORKER}"
_WORKER_URL = _TEST_DB_BASE.set(database=_WORKER_DB)
_ADMIN_URL = _TEST_DB_BASE.set(database="postgres")

# Anything that reads DATABASE_URL at import time (settings singleton, the
# module-level engine in saz.db.session) must see this worker's database.
os.environ["DATABASE_URL"] = _WORKER_URL.render_as_string(hide_password=False)


def _admin_exec(statements: list[str]) -> None:
    """Run AUTOCOMMIT maintenance statements against the ``postgres`` database."""
    admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            for stmt in statements:
                conn.exec_driver_sql(stmt)
    finally:
        admin.dispose()


def _drop_db_statements(name: str) -> list[str]:
    return [
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{name}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{name}"',
    ]


# Create the worker database up front so importing the app (which builds a
# module-level engine) and the first test both see a live database.
_admin_exec([*_drop_db_statements(_WORKER_DB), f'CREATE DATABASE "{_WORKER_DB}"'])


def pytest_unconfigure(config):  # noqa: ARG001
    """Drop this worker's database when the session ends."""
    _admin_exec(_drop_db_statements(_WORKER_DB))


# Imported after the worker database is created above so importing the app
# (which builds a module-level engine) sees a live database.
from saz.agents import LLMPort, LLMResponse  # noqa: E402
from saz.api.app import app  # noqa: E402
from saz.api.dependencies import get_current_user  # noqa: E402
from saz.db.dependencies import get_uow  # noqa: E402
from saz.db.models import Base, User  # noqa: E402
from saz.db.unit_of_work import UnitOfWork  # noqa: E402
from saz.security import hash_password  # noqa: E402

# Fixed test-user id used everywhere a test inserts a Flow/Run/Credential
# directly. The `users` row is seeded into every fresh test database by the
# ``db_engine`` fixture so all FKs resolve without each test having to
# coordinate with the auth fixtures.
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_USER_USERNAME = "testuser"
TEST_USER_EMAIL = "testuser@example.com"
TEST_USER_PASSWORD = "test-password-123"


def _seed_test_user(engine) -> None:
    """Seed the canonical test user so direct ORM inserts of Flow/Run/Credential
    rows resolve their NOT NULL ``created_by_user_id`` FK without each test
    managing the auth fixture chain."""
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


@pytest.fixture(scope="session")
def _pg_engine():
    """One PostgreSQL engine per xdist worker; schema built from the ORM models.

    The worker database is created (and dropped) around the whole session in
    module-level setup/``pytest_unconfigure``; here we just build the schema.
    """
    engine = create_engine(_WORKER_URL, pool_pre_ping=True, pool_size=5, max_overflow=5)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


def seed_run(
    engine,
    run_id: str,
    *,
    status: str = "running",
    flow_id: str = "flow_seed",
    step_ids: list[str] | None = None,
) -> str:
    """Insert a Run (plus a shared parent Flow, and any requested Steps) so
    events/steps referencing them satisfy PostgreSQL foreign keys. Idempotent.

    SQLite did not enforce these FKs, so many event/run tests historically used
    bare ``run_id``/``step_id`` strings; on PostgreSQL the parent rows must exist.
    """
    from saz.db.models import Flow, Run, Step

    session = sessionmaker(bind=engine)()
    try:
        now = datetime.now(UTC)
        if session.get(Flow, flow_id) is None:
            session.add(
                Flow(
                    id=flow_id,
                    name=f"seed-flow-{flow_id}",
                    definition={},
                    created_by_user_id=TEST_USER_ID,
                    created_at=now,
                )
            )
            session.flush()
        if session.get(Run, run_id) is None:
            session.add(
                Run(
                    id=run_id,
                    flow_id=flow_id,
                    status=status,
                    payload={},
                    created_by_user_id=TEST_USER_ID,
                    created_at=now,
                )
            )
            session.flush()
        for i, step_id in enumerate(step_ids or [], start=1):
            if session.get(Step, step_id) is None:
                session.add(
                    Step(
                        id=step_id,
                        run_id=run_id,
                        number=i,
                        name=step_id,
                        step_type="tool.call",
                        status="completed",
                    )
                )
        session.commit()
    finally:
        session.close()
    return run_id


@pytest.fixture(scope="function")
def db_engine(_pg_engine):
    """Per-test clean database: truncate every table and reseed the test user.

    Faster than create_all/drop_all per test while keeping full PostgreSQL
    semantics (FK enforcement, JSON, real transactions).
    """
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with _pg_engine.begin() as conn:
        conn.exec_driver_sql(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
    _seed_test_user(_pg_engine)
    yield _pg_engine


@pytest.fixture(scope="function")
def sync_executor(db_engine):
    """Override scheduler to use synchronous execution for tests.

    ``RunScheduler`` is a classic singleton (``__new__`` caches
    ``_instance``), so naively constructing ``SyncScheduler(...)`` here
    returns the same object as any previous test's scheduler. We must clear
    the class-level singleton state before instantiating so the scheduler binds
    to this test's ``db_engine`` rather than a stale one from a prior test.
    """
    from saz.engine.scheduler import RunScheduler, _scheduler_lock

    # Get the database URL from the engine. render_as_string(hide_password=False)
    # is required: str(url) masks the password as "***", which makes the
    # scheduler's per-thread engine fail PostgreSQL authentication.
    database_url = db_engine.url.render_as_string(hide_password=False)

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

        # Reset the class-level singleton so the new SyncScheduler is a
        # genuinely fresh instance bound to this test's db_engine.
        # Without this, RunScheduler.__new__ returns the previous test's
        # scheduler (with its disposed engine), and resume/schedule calls
        # blow up with "no such table: runs".
        RunScheduler._instance = None
        sched_module._scheduler = SyncScheduler(database_url)

        yield sched_module._scheduler

        # Cleanup
        if sched_module._scheduler:
            try:
                sched_module._scheduler.shutdown(wait=True)
            except Exception:
                pass
        sched_module._scheduler = original_scheduler
        # Leave the singleton cleared so the next test's fixture also
        # gets a fresh instance.
        RunScheduler._instance = None


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


@pytest.fixture(autouse=True)
def _isolate_llm_port():
    """Guarantee no test ever calls a real LLM.

    The human.approval path generates an approval brief via the global LLM
    port, so a default LiteLLM port would make a network call when a run hits
    an approval gate. Install a deterministic mock for every test and reset the
    cached AI runner. Tests needing specific LLM behavior override the port in
    the test body via ``set_llm_port(...)``.
    """
    from saz.agents import ai_ops, llm_port as llm_port_module
    from saz.settings import settings

    previous_port = llm_port_module._default_port
    previous_runner = ai_ops._ai_runner
    previous_lint_llm = settings.LINT_LLM_ENABLED
    llm_port_module.set_llm_port(MockLLMPort())
    ai_ops._ai_runner = None
    # Flow-lint LLM rule off by default in tests (deterministic rules still run);
    # tests exercising it opt in explicitly and inject a fake port.
    settings.LINT_LLM_ENABLED = False
    try:
        yield
    finally:
        llm_port_module._default_port = previous_port
        ai_ops._ai_runner = previous_runner
        settings.LINT_LLM_ENABLED = previous_lint_llm


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
