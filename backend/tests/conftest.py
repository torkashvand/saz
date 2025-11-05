"""Pytest configuration and shared fixtures for tests."""
import os
import json
from typing import List, Dict, Optional
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Set test DATABASE_URL before importing saz modules
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from saz.db.models import Base
from saz.db import get_db
from saz.api import app
from saz.agents.llm_port import LLMPort, LLMResponse


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
    """Create FastAPI test client with database override."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


class MockLLMPort(LLMPort):
    """Mock LLM port for testing - returns fixed responses."""

    def __init__(self, responses: Optional[List[str]] = None):
        """
        Initialize mock LLM port.

        Args:
            responses: List of response strings to return in sequence.
                      If None, returns default success response.
        """
        self.responses = responses or []
        self.call_count = 0
        self.calls = []  # Track all calls for assertions

    async def complete(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, str]] = None,
        timeout: int = 30
    ) -> LLMResponse:
        """Return fixed response and track call."""
        # Record call details
        self.calls.append({
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format
        })

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
            content=content,
            total_tokens=100,
            prompt_tokens=50,
            completion_tokens=50,
            model=model
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
                "action": "tool_call",
                "tool_name": "http_request",
                "input_template": {"url": "https://example.com"},
                "expected_output_schema": {"type": "object"},
                "error_handling": "retry",
                "max_retries": 3,
                "reasoning": "Test step"
            }
        ],
        "estimated_cost_usd": 0.001,
        "estimated_time_seconds": 5,
        "reasoning": "Test plan"
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
        "confidence": 0.95
    }
    mock_llm_port.responses = [json.dumps(critique)]
    return mock_llm_port
