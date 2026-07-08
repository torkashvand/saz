"""Tests for flow detail and graph endpoints — verifying correct data paths."""

import pytest

MINIMAL_YAML = """
schema_version: 1
flow:
  name: TestDetailFlow
  version: "2.0"
  description: Flow for testing detail endpoint

form:
  fields:
    - name: input_text
      type: string
      required: true
      description: Input text

workflow:
  planner_mode: deterministic
  steps:
    - id: step_extract
      type: ai.extract
      instruction: "Extract entities from text"
      expect:
        properties:
          entities:
            type: array
            items: { type: string }
        required: [entities]
    - id: step_generate
      type: ai.generate
      instruction: "Generate summary"
      expect:
        properties:
          output: { type: string }
        required: [output]

policies:
  budget_usd: 0.25

credentials:
  uses: []
"""

YAML_WITH_CONDITION = """
schema_version: 1
flow:
  name: ConditionFlow
  version: "1.0"
  description: Flow with condition step

form:
  fields:
    - name: value
      type: integer
      required: true

workflow:
  planner_mode: deterministic
  steps:
    - id: step_check
      type: condition
      description: "Check threshold"
      if: "$form.value > 10"
    - id: step_action
      type: ai.generate
      instruction: "Generate result"
      expect:
        properties:
          output: { type: string }
        required: [output]

policies:
  budget_usd: 0.10

credentials:
  uses: []
"""

YAML_WITH_ROUTE = """
schema_version: 1
flow:
  name: RouteFlow
  version: "1.0"
  description: Flow with routing

form:
  fields:
    - name: message
      type: string
      required: true

workflow:
  planner_mode: deterministic
  steps:
    - id: step_route
      type: ai.route
      instruction: "Route message to team"
      branches_enum:
        - support
        - engineering
        - sales
      expect:
        properties:
          branch:
            type: string
            enum: [support, engineering, sales]
        required: [branch]
    - id: step_handle
      type: ai.generate
      instruction: "Generate response"
      expect:
        properties:
          output: { type: string }
        required: [output]

policies:
  budget_usd: 0.10

credentials:
  uses: []
"""


@pytest.fixture
def registered_flow(app_client):
    """Register a flow and return its ID."""
    resp = app_client.post("/api/v1/flows", json={"yaml": MINIMAL_YAML})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.fixture
def registered_condition_flow(app_client):
    resp = app_client.post("/api/v1/flows", json={"yaml": YAML_WITH_CONDITION})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.fixture
def registered_route_flow(app_client):
    resp = app_client.post("/api/v1/flows", json={"yaml": YAML_WITH_ROUTE})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# FlowDetail endpoint
# ---------------------------------------------------------------------------


def test_step_count_from_workflow_steps(app_client, registered_flow):
    """step_count should reflect workflow.steps, not root definition.steps."""
    resp = app_client.get(f"/api/v1/flows/{registered_flow}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["step_count"] == 2


def test_policies_from_root_definition(app_client, registered_flow):
    """policies.max_cost_usd should map from root policies.budget_usd."""
    resp = app_client.get(f"/api/v1/flows/{registered_flow}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["policies"]["max_cost_usd"] == 0.25


def test_planner_mode(app_client, registered_flow):
    resp = app_client.get(f"/api/v1/flows/{registered_flow}")
    assert resp.status_code == 200
    assert resp.json()["planner_mode"] == "deterministic"


def test_list_includes_planner_mode(app_client, registered_flow):
    """The list endpoint must expose planner_mode — the catalog UI filters
    and badges flows by it."""
    resp = app_client.get("/api/v1/flows")
    assert resp.status_code == 200
    items = resp.json()["items"]
    item = next(i for i in items if i["id"] == registered_flow)
    assert item["planner_mode"] == "deterministic"


def test_flow_metadata(app_client, registered_flow):
    resp = app_client.get(f"/api/v1/flows/{registered_flow}")
    data = resp.json()
    assert data["name"] == "TestDetailFlow"
    assert data["version"] == "2.0"
    assert data["description"] == "Flow for testing detail endpoint"


def test_original_yaml_preserved(app_client, registered_flow):
    resp = app_client.get(f"/api/v1/flows/{registered_flow}")
    data = resp.json()
    assert data["original_yaml"] is not None
    assert "TestDetailFlow" in data["original_yaml"]


def test_definition_contains_workflow(app_client, registered_flow):
    resp = app_client.get(f"/api/v1/flows/{registered_flow}")
    data = resp.json()
    assert "workflow" in data["definition"]
    assert "steps" in data["definition"]["workflow"]


def test_flow_not_found(app_client):
    resp = app_client.get("/api/v1/flows/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# FlowGraph endpoint
# ---------------------------------------------------------------------------


def test_graph_nodes_match_steps(app_client, registered_flow):
    resp = app_client.get(f"/api/v1/flows/{registered_flow}/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == 2
    assert data["nodes"][0]["id"] == "step_extract"
    assert data["nodes"][1]["id"] == "step_generate"


def test_graph_linear_edges(app_client, registered_flow):
    resp = app_client.get(f"/api/v1/flows/{registered_flow}/graph")
    data = resp.json()
    assert len(data["edges"]) == 1
    assert data["edges"][0]["from"] == "step_extract"
    assert data["edges"][0]["to"] == "step_generate"


def test_graph_node_types(app_client, registered_flow):
    resp = app_client.get(f"/api/v1/flows/{registered_flow}/graph")
    data = resp.json()
    assert data["nodes"][0]["type"] == "ai.extract"
    assert data["nodes"][1]["type"] == "ai.generate"


def test_graph_condition_edge_label(app_client, registered_condition_flow):
    """Edges after condition steps should have 'true' label."""
    resp = app_client.get(f"/api/v1/flows/{registered_condition_flow}/graph")
    data = resp.json()
    assert len(data["edges"]) == 1
    assert data["edges"][0]["label"] == "true"


def test_graph_route_edge_label(app_client, registered_route_flow):
    """Edges after ai.route steps should have 'routed' label."""
    resp = app_client.get(f"/api/v1/flows/{registered_route_flow}/graph")
    data = resp.json()
    assert len(data["edges"]) == 1
    assert data["edges"][0]["label"] == "routed"


def test_graph_not_found(app_client):
    resp = app_client.get("/api/v1/flows/nonexistent-id/graph")
    assert resp.status_code == 404


def test_graph_empty_workflow(app_client):
    """Flow with no steps should produce empty graph.

    Deterministic mode requires non-empty steps, so empty-step flows must
    be agentic — the planner generates the plan at runtime. The graph
    endpoint walks definition.workflow.steps which is empty here.
    """
    yaml_content = """
schema_version: 1
flow:
  name: EmptyFlow
  version: "1.0"
  description: No steps
workflow:
  planner_mode: agentic
  steps: []
policies:
  budget_usd: 0.01
credentials:
  uses: []
"""
    resp = app_client.post("/api/v1/flows", json={"yaml": yaml_content})
    assert resp.status_code == 200
    flow_id = resp.json()["id"]

    resp = app_client.get(f"/api/v1/flows/{flow_id}/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert data["nodes"] == []
    assert data["edges"] == []
