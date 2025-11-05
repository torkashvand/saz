"""Unit tests for API helper functions - graph building and validation."""
import pytest
from datetime import datetime, UTC
from saz.api_helpers import (
    build_flow_graph,
    build_run_status_map,
    validate_form_payload,
    extract_step_details
)


def test_build_flow_graph_simple_workflow():
    """Test building graph from simple linear workflow."""
    workflow_spec = {
        "steps": [
            {"id": "step1", "type": "tool_call", "description": "First step"},
            {"id": "step2", "type": "ai.assess", "description": "Second step"},
            {"id": "step3", "type": "tool_call", "description": "Third step"}
        ]
    }

    graph = build_flow_graph(workflow_spec)

    # Verify nodes
    assert len(graph["nodes"]) == 3
    assert graph["nodes"][0]["id"] == "step1"
    assert graph["nodes"][0]["label"] == "First step"
    assert graph["nodes"][0]["type"] == "tool_call"

    # Verify linear edges
    assert len(graph["edges"]) == 2
    assert graph["edges"][0] == {"from": "step1", "to": "step2"}
    assert graph["edges"][1] == {"from": "step2", "to": "step3"}


def test_build_flow_graph_with_ai_route():
    """Test building graph with AI routing branches."""
    workflow_spec = {
        "steps": [
            {"id": "step1", "type": "tool_call", "description": "Initial step"},
            {
                "id": "router",
                "type": "ai.route",
                "description": "Route decision",
                "branches_enum": ["high_risk", "low_risk"]
            },
            {"id": "step3", "type": "tool_call", "description": "Final step"}
        ]
    }

    graph = build_flow_graph(workflow_spec)

    # Verify nodes
    assert len(graph["nodes"]) == 3

    # Verify edges include branch edges
    assert len(graph["edges"]) == 4  # 2 linear + 2 branches

    # Check linear edges
    assert {"from": "step1", "to": "router"} in graph["edges"]
    assert {"from": "router", "to": "step3"} in graph["edges"]

    # Check branch edges
    assert {"from": "router", "to": "router_branch_high_risk", "label": "high_risk"} in graph["edges"]
    assert {"from": "router", "to": "router_branch_low_risk", "label": "low_risk"} in graph["edges"]


def test_build_flow_graph_empty_workflow():
    """Test building graph from empty workflow."""
    workflow_spec = {"steps": []}

    graph = build_flow_graph(workflow_spec)

    assert graph["nodes"] == []
    assert graph["edges"] == []


def test_build_flow_graph_single_step():
    """Test building graph with single step."""
    workflow_spec = {
        "steps": [
            {"id": "only_step", "type": "tool_call", "description": "Only step"}
        ]
    }

    graph = build_flow_graph(workflow_spec)

    assert len(graph["nodes"]) == 1
    assert graph["edges"] == []  # No edges for single step


def test_build_flow_graph_steps_without_ids():
    """Test building graph with steps missing IDs (uses fallback)."""
    workflow_spec = {
        "steps": [
            {"type": "tool_call"},
            {"type": "ai.assess"}
        ]
    }

    graph = build_flow_graph(workflow_spec)

    # Should use fallback IDs
    assert graph["nodes"][0]["id"] == "step_0"
    assert graph["nodes"][1]["id"] == "step_1"
    assert graph["edges"][0] == {"from": "step_0", "to": "step_1"}


def test_build_run_status_map():
    """Test building status map for run graph."""
    # Mock run steps
    class MockStep:
        def __init__(self, step_name, status):
            self.step_name = step_name
            self.status = status

    run_steps = [
        MockStep("step1", "success"),
        MockStep("step2", "success"),
        MockStep("step3", "failed")
    ]

    workflow_spec = {
        "steps": [
            {"id": "step1"},
            {"id": "step2"},
            {"id": "step3"},
            {"id": "step4"},
            {"id": "step5"}
        ]
    }

    status_map = build_run_status_map(run_steps, workflow_spec)

    # Verify executed steps have actual status
    assert status_map["step1"] == "success"
    assert status_map["step2"] == "success"
    assert status_map["step3"] == "failed"

    # Verify pending steps
    assert status_map["step4"] == "pending"
    assert status_map["step5"] == "pending"


def test_build_run_status_map_all_completed():
    """Test status map when all steps are completed."""
    class MockStep:
        def __init__(self, step_name, status):
            self.step_name = step_name
            self.status = status

    run_steps = [
        MockStep("step1", "success"),
        MockStep("step2", "success")
    ]

    workflow_spec = {
        "steps": [
            {"id": "step1"},
            {"id": "step2"}
        ]
    }

    status_map = build_run_status_map(run_steps, workflow_spec)

    assert status_map["step1"] == "success"
    assert status_map["step2"] == "success"
    assert len(status_map) == 2


def test_validate_form_payload_valid():
    """Test validation with valid payload."""
    payload = {
        "username": "test_user",
        "email": "test@example.com",
        "age": 25
    }

    form_schema = {
        "required": ["username", "email"]
    }

    is_valid, error = validate_form_payload(payload, form_schema)

    assert is_valid is True
    assert error is None


def test_validate_form_payload_missing_required():
    """Test validation fails with missing required field."""
    payload = {
        "username": "test_user"
    }

    form_schema = {
        "required": ["username", "email", "age"]
    }

    is_valid, error = validate_form_payload(payload, form_schema)

    assert is_valid is False
    assert "Missing required field: email" in error


def test_validate_form_payload_no_required_fields():
    """Test validation passes when no fields are required."""
    payload = {"optional_field": "value"}

    form_schema = {}  # No required fields

    is_valid, error = validate_form_payload(payload, form_schema)

    assert is_valid is True
    assert error is None


def test_validate_form_payload_empty():
    """Test validation with empty payload fails for required fields."""
    payload = {}

    form_schema = {
        "required": ["username"]
    }

    is_valid, error = validate_form_payload(payload, form_schema)

    assert is_valid is False
    assert "username" in error


def test_extract_step_details():
    """Test extracting step details with artifacts and costs."""
    # Mock run steps
    class MockStep:
        def __init__(self, step_name, status, tokens, cost, artifacts):
            self.step_name = step_name
            self.status = status
            self.tokens = tokens
            self.cost_usd = cost
            self.artifacts = artifacts
            self.input_data = {"type": "test"}
            self.output_data = {"result": "success"}
            self.error = None
            self.started_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
            self.completed_at = datetime(2025, 1, 1, 12, 0, 5, tzinfo=UTC)

    run_steps = [
        MockStep("step1", "success", 100, 0.001, ["artifact1"]),
        MockStep("step2", "success", 200, 0.002, ["artifact2", "artifact3"]),
        MockStep("step3", "failed", None, None, None)
    ]

    steps_detail, artifacts_list, total_tokens, total_cost = extract_step_details(run_steps)

    # Verify step details
    assert len(steps_detail) == 3
    assert steps_detail[0]["id"] == "step1"
    assert steps_detail[0]["status"] == "success"
    assert steps_detail[0]["tokens"] == 100
    assert steps_detail[0]["cost_usd"] == 0.001
    assert steps_detail[0]["duration_ms"] == 5000  # 5 seconds

    # Verify artifacts
    assert len(artifacts_list) == 3
    assert "artifact1" in artifacts_list
    assert "artifact2" in artifacts_list
    assert "artifact3" in artifacts_list

    # Verify totals
    assert total_tokens == 300
    assert total_cost == 0.003


def test_extract_step_details_no_artifacts():
    """Test extracting details when steps have no artifacts."""
    class MockStep:
        def __init__(self):
            self.step_name = "test_step"
            self.status = "success"
            self.tokens = None
            self.cost_usd = None
            self.artifacts = None
            self.input_data = None
            self.output_data = None
            self.error = None
            self.started_at = datetime.now(UTC)
            self.completed_at = None  # Not completed yet

    run_steps = [MockStep()]

    steps_detail, artifacts_list, total_tokens, total_cost = extract_step_details(run_steps)

    assert len(steps_detail) == 1
    assert steps_detail[0]["duration_ms"] is None  # Not completed
    assert artifacts_list == []
    assert total_tokens == 0
    assert total_cost == 0.0


def test_extract_step_details_with_errors():
    """Test extracting details from failed steps."""
    class MockStep:
        def __init__(self):
            self.step_name = "failing_step"
            self.status = "failed"
            self.tokens = 50
            self.cost_usd = 0.0005
            self.artifacts = None
            self.input_data = {"input": "data"}
            self.output_data = None
            self.error = "Connection timeout"
            self.started_at = datetime.now(UTC)
            self.completed_at = datetime.now(UTC)

    run_steps = [MockStep()]

    steps_detail, artifacts_list, total_tokens, total_cost = extract_step_details(run_steps)

    assert steps_detail[0]["status"] == "failed"
    assert steps_detail[0]["error"] == "Connection timeout"
    assert steps_detail[0]["output"] is None
    assert total_tokens == 50


def test_build_flow_graph_description_fallback():
    """Test graph building with missing descriptions."""
    workflow_spec = {
        "steps": [
            {"id": "step1", "type": "tool_call"},  # No description
            {"id": "step2", "type": "ai.assess", "description": "Has description"}
        ]
    }

    graph = build_flow_graph(workflow_spec)

    # Should use step ID as label fallback
    assert graph["nodes"][0]["label"] == "step1"
    assert graph["nodes"][1]["label"] == "Has description"
