"""Test the /api/v1/flows/compile endpoint."""

from fastapi.testclient import TestClient

from saz.api import app

client = TestClient(app)


def test_compile_valid_flow():
    """Test compiling a valid flow YAML."""
    yaml_content = """
flow:
  name: TestFlow
  version: "1.0"
  description: Test workflow

form:
  fields:
    - name: username
      type: text
      required: true
      regex: "^[a-z0-9_]+$"
      description: Username
    - name: count
      type: number
      required: true
      min: 1
      max: 100

workflow:
  steps:
    - id: step1
      type: http.request
      url: "https://api.example.com/test"
    - id: step2
      type: ai.extract
      instruction: Extract data

credentials:
  uses:
    - api_key
"""

    response = client.post("/api/v1/flows/compile", json={"yaml": yaml_content})

    assert response.status_code == 200
    data = response.json()

    # Check response structure
    assert data["flow_name"] == "TestFlow"
    assert data["flow_version"] == "1.0"
    assert data["flow_description"] == "Test workflow"

    # Check form schema
    assert "form_schema" in data
    schema = data["form_schema"]
    assert "properties" in schema
    assert "username" in schema["properties"]
    assert "count" in schema["properties"]
    assert schema["properties"]["username"]["type"] == "string"
    assert schema["properties"]["count"]["type"] == "integer"

    # Check workflow summary
    assert data["workflow_summary"]["steps_count"] == 2
    assert data["workflow_summary"]["ai_steps"] == 1
    assert "api_key" in data["workflow_summary"]["credentials"]


def test_compile_invalid_yaml():
    """Test compiling invalid YAML."""
    yaml_content = """
flow:
  name: InvalidFlow
# Missing workflow section (workflow is required)
"""

    response = client.post("/api/v1/flows/compile", json={"yaml": yaml_content})

    assert response.status_code == 400
    assert "error" in response.json()


def test_compile_missing_required_fields():
    """Test compiling YAML with missing required fields."""
    yaml_content = """
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
