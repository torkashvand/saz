"""Test the /api/v1/flows/compile endpoint (strict DSL)."""

from fastapi.testclient import TestClient

from saz.api import app

client = TestClient(app)


def test_compile_valid_flow():
    """Compiles a valid, strict DSL flow."""
    yaml_content = """
schema_version: 1
flow:
  name: TestFlow
  version: "1.0"
  description: Test workflow

form:
  fields:
    - name: username
      type: string
      required: true
      pattern: "^[a-z0-9_]+$"
      description: Username
    - name: count
      type: integer
      required: true
      minimum: 1
      maximum: 100

workflow:
  steps:
    - id: step1
      type: tool.call
      tool: http_request
      params:
        url: "https://api.example.com/test"
    - id: step2
      type: ai.extract
      instruction: "Extract data"

credentials:
  - name: api_key
"""

    response = client.post("/api/v1/flows/compile", json={"yaml": yaml_content})
    assert response.status_code == 200
    data = response.json()

    # Flow metadata
    assert data["flow_name"] == "TestFlow"
    assert data["flow_version"] == "1.0"
    assert data["flow_description"] == "Test workflow"

    # Form schema
    schema = data["form_schema"]
    assert "properties" in schema
    assert "username" in schema["properties"]
    assert "count" in schema["properties"]
    assert schema["properties"]["username"]["type"] == "string"
    assert schema["properties"]["count"]["type"] == "integer"

    # Workflow summary
    assert data["workflow_summary"]["steps_count"] == 2
    assert data["workflow_summary"]["ai_steps"] == 1
    assert "api_key" in data["workflow_summary"]["credentials"]


def test_compile_invalid_yaml():
    """Bad YAML should produce 400 with an error body."""
    yaml_content = """
flow:
  name: InvalidFlow
# Missing workflow and schema_version
"""
    response = client.post("/api/v1/flows/compile", json={"yaml": yaml_content})
    assert response.status_code == 400
    assert "error" in response.json()


def test_compile_missing_required_fields():
    """Missing required top-level keys should be rejected."""
    yaml_content = """
schema_version: 1
flow:
  description: Missing name
form:
  fields: []
workflow:
  steps: []
"""
    response = client.post("/api/v1/flows/compile", json={"yaml": yaml_content})
    assert response.status_code == 400
    assert "error" in response.json()
