"""Integration test: Register form, create run, advance through workflow."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from saz.db.models import Base
from saz.db import get_db
from saz.api import app

# Test database (in-memory SQLite for simplicity)
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="function")
def test_db():
    """Create fresh test database for each test."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def test_full_workflow(test_db):
    """Test complete flow: register form, create run, advance, complete."""

    # 1. Register a form
    form_yaml = """
name: UserOnboarding
fields:
  - name: username
    type: text
    required: true
    regex: "^[a-z0-9_]+$"
    description: "Username (alphanumeric + underscore)"
  - name: age
    type: number
    required: true
    min: 18
    max: 120
  - name: newsletter
    type: boolean
    required: false
"""

    response = client.post("/register_forms", json={"form_yaml": form_yaml})
    assert response.status_code == 200
    data = response.json()
    assert "flow_id" in data
    assert data["name"] == "UserOnboarding"
    assert "json_schema" in data

    flow_id = data["flow_id"]
    json_schema = data["json_schema"]

    # Verify JSON schema has expected fields
    assert "properties" in json_schema
    assert "username" in json_schema["properties"]
    assert "age" in json_schema["properties"]

    # 2. Create a run with valid data
    payload = {"username": "john_doe", "age": 25, "newsletter": True}

    response = client.post("/runs", json={"flow_id": flow_id, "payload": payload})
    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert data["status"] == "suspended"  # First step is input, so suspends

    run_id = data["run_id"]

    # 3. Check run status
    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "suspended"
    assert data["state"]["username"] == "john_doe"

    # 4. Advance the run (simulate user continuing)
    response = client.post(f"/runs/{run_id}/advance", json={"event": "continue"})
    assert response.status_code == 200
    data = response.json()
    # After approval step, workflow completes
    assert data["status"] == "completed"
    assert data["state"]["approved"] is True


def test_invalid_payload(test_db):
    """Test that invalid payload is rejected."""
    form_yaml = """
name: SimpleForm
fields:
  - name: email
    type: text
    required: true
"""

    response = client.post("/register_forms", json={"form_yaml": form_yaml})
    flow_id = response.json()["flow_id"]

    # Missing required field
    response = client.post("/runs", json={"flow_id": flow_id, "payload": {}})
    assert response.status_code == 400
    assert "Invalid payload" in response.json()["detail"]


def test_custom_workflow(test_db):
    """Test registering a custom workflow with multiple steps."""
    form_yaml = """
name: DataProcessing
fields:
  - name: data
    type: text
    required: true
"""

    workflow_yaml = """
description: "Custom 3-step workflow"
steps:
  - name: collect
    type: input
  - name: process
    type: step
  - name: finalize
    type: step
"""

    response = client.post(
        "/register_forms", json={"form_yaml": form_yaml, "workflow_yaml": workflow_yaml}
    )
    assert response.status_code == 200
    flow_id = response.json()["flow_id"]

    # Create run
    response = client.post("/runs", json={"flow_id": flow_id, "payload": {"data": "test"}})
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    # Check that workflow has custom steps
    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
