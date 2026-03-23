"""API tests for the AI Operations Reference endpoint.

Proves that GET /api/v1/flows/ai-ops returns correct operation metadata
for the flow builder's AI Ops Reference panel.
"""

from saz.agents.ai_ops import AI_OPS


def test_ai_ops_endpoint_returns_operations(app_client):
    """Endpoint returns all user-facing AI operations."""
    response = app_client.get("/api/v1/flows/ai-ops")
    assert response.status_code == 200

    ops = response.json()
    assert isinstance(ops, list)
    # Should have all ops except ai.fix_json (internal)
    assert len(ops) == len(AI_OPS) - 1

    names = [op["name"] for op in ops]
    assert "ai.extract" in names
    assert "ai.route" in names
    assert "ai.score" in names
    assert "ai.generate" in names
    assert "ai.assess" in names
    # ai.fix_json is internal and should not be exposed
    assert "ai.fix_json" not in names


def test_ai_ops_endpoint_returns_correct_fields(app_client):
    """Each operation has name, description, output_format, default_output_schema, extras."""
    response = app_client.get("/api/v1/flows/ai-ops")
    ops = response.json()

    for op in ops:
        assert "name" in op
        assert "description" in op
        assert "output_format" in op
        assert "default_output_schema" in op
        assert "extras" in op
        assert op["output_format"] in ("json", "text")


def test_ai_ops_endpoint_route_has_extras(app_client):
    """ai.route should expose branches_enum in extras."""
    response = app_client.get("/api/v1/flows/ai-ops")
    ops = {op["name"]: op for op in response.json()}

    route_op = ops["ai.route"]
    assert "branches_enum" in route_op["extras"]


def test_ai_ops_endpoint_score_has_bounds(app_client):
    """ai.score default schema should have score with min/max bounds."""
    response = app_client.get("/api/v1/flows/ai-ops")
    ops = {op["name"]: op for op in response.json()}

    score_op = ops["ai.score"]
    schema = score_op["default_output_schema"]
    assert "properties" in schema
    assert "score" in schema["properties"]
    assert schema["properties"]["score"]["minimum"] == 0
    assert schema["properties"]["score"]["maximum"] == 1


def test_ai_ops_endpoint_extract_is_flexible(app_client):
    """ai.extract default schema should have additionalProperties: true."""
    response = app_client.get("/api/v1/flows/ai-ops")
    ops = {op["name"]: op for op in response.json()}

    extract_op = ops["ai.extract"]
    schema = extract_op["default_output_schema"]
    assert schema.get("additionalProperties") is True
