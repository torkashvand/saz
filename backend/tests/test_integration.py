"""Integration test: Register flows, create runs, test workflow APIs."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from saz.db.models import Base
from saz.db.dependencies import get_uow
from saz.db.unit_of_work import UnitOfWork
from saz.api import app

# Test database (in-memory SQLite for simplicity)
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_uow():
    session = TestingSessionLocal()
    try:
        yield UnitOfWork(session)
    finally:
        session.close()


app.dependency_overrides[get_uow] = override_get_uow


@pytest.fixture(scope="function")
def test_db():
    """Create fresh test database for each test."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def test_full_workflow(test_db):
    """Test complete flow: register flow, list flows, get flow detail."""

    # 1. Register a flow
    dsl_yaml = """
flow:
  name: UserOnboarding
  version: "1.0"
  description: "User onboarding workflow"
form:
  fields:
    - name: username
      type: text
      required: true
    - name: email
      type: text
      required: true
workflow:
  steps:
    - id: step1
      type: api_call
      description: "Create user account"
"""

    response = client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["name"] == "UserOnboarding"

    flow_id = data["id"]

    # 2. List flows
    response = client.get("/api/v1/flows")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "UserOnboarding"

    # 3. Get flow detail
    response = client.get(f"/api/v1/flows/{flow_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "UserOnboarding"
    assert data["version"] == "1.0"
    assert "definition" in data


def test_run_creation(test_db):
    """Test creating and listing runs."""
    # 1. Register a flow first
    dsl_yaml = """
flow:
  name: SimpleFlow
workflow:
  steps:
    - id: step1
      type: api_call
"""
    response = client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    assert response.status_code == 200
    flow_id = response.json()["id"]

    # 2. Create a run
    response = client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {"data": "test"}})
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["flow_id"] == flow_id
    assert data["status"] == "queued"

    run_id = data["id"]

    # 3. List runs
    response = client.get("/api/v1/runs")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["flow_id"] == flow_id

    # 4. Get run detail
    response = client.get(f"/api/v1/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == run_id
    assert data["flow_id"] == flow_id
    assert "steps" in data


def test_credentials(test_db):
    """Test credential CRUD operations."""
    # 1. Create a credential
    response = client.post(
        "/api/v1/credentials",
        json={
            "name": "test_api_key",
            "credential_type": "api_token",
            "data": {"token": "secret123", "endpoint": "https://api.example.com"},
            "description": "Test API key"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test_api_key"
    assert data["type"] == "api_token"

    # 2. List credentials
    response = client.get("/api/v1/credentials")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] == 1
    assert data["items"][0]["name"] == "test_api_key"

    # 3. Update credential
    response = client.put(
        "/api/v1/credentials/test_api_key",
        json={
            "data": {"token": "newsecret456", "endpoint": "https://api.example.com"},
            "description": "Updated API key"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test_api_key"

    # 4. Delete credential
    response = client.delete("/api/v1/credentials/test_api_key")
    assert response.status_code == 200
    assert response.json()["status"] == "deleted"

    # 5. Verify deleted
    response = client.get("/api/v1/credentials")
    assert response.status_code == 200
    assert response.json()["total"] == 0
