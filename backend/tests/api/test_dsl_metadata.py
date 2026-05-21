"""Contract: /api/v1/flows/dsl-metadata exposes the canonical DSL surface.

The Guided Builder reads from this endpoint to know which step types are
authorable, what fields each one requires, and which expression helpers /
tools are available. If this drifts from the compiler, guided edits start
producing invalid YAML.
"""


def test_dsl_metadata_returns_all_user_facing_step_types(app_client):
    response = app_client.get("/api/v1/flows/dsl-metadata")
    assert response.status_code == 200
    data = response.json()
    types = {t["name"] for t in data["step_types"]}

    expected = {
        "tool.call",
        "condition",
        "human.approval",
        "webhook.wait",
        "artifact.store",
        "artifact.retrieve",
        "ai.extract",
        "ai.generate",
        "ai.route",
        "ai.score",
        "ai.assess",
        "ai.normalize",
        "ai.match",
        "ai.evaluate",
        "ai.compare",
        "ai.translate",
        "ai.summarize",
        "ai.plan",
    }
    assert expected <= types
    # `ai.fix_json` is an internal repair op; not user-facing.
    assert "ai.fix_json" not in types


def test_dsl_metadata_planner_modes(app_client):
    data = app_client.get("/api/v1/flows/dsl-metadata").json()
    assert data["planner_modes"] == ["deterministic", "agentic"]


def test_dsl_metadata_expression_helpers(app_client):
    data = app_client.get("/api/v1/flows/dsl-metadata").json()
    names = {h["name"] for h in data["expression_helpers"]}
    assert {"$form", "$step", "$env", "$secret"} <= names


def test_dsl_metadata_ai_step_carries_op_spec(app_client):
    data = app_client.get("/api/v1/flows/dsl-metadata").json()
    by_name = {t["name"]: t for t in data["step_types"]}
    assess = by_name["ai.assess"]
    assert "ai_op" in assess
    assert assess["ai_op"]["output_format"] in {"json", "text"}
    assert assess["requires_instruction"] is True
    assert assess["requires_expect"] is True


def test_dsl_metadata_form_field_types(app_client):
    data = app_client.get("/api/v1/flows/dsl-metadata").json()
    assert set(data["form_fields"]["types"]) == {
        "string",
        "integer",
        "number",
        "boolean",
        "text",
    }
    # Backend accepts `regex` as alias for `pattern` etc — the contract surfaces it.
    aliases = data["form_fields"]["aliases"]
    assert "regex" in aliases["pattern"]
    assert "min" in aliases["minimum"]
