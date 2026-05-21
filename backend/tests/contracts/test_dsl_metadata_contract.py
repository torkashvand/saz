"""Contract snapshot: /api/v1/flows/dsl-metadata response shape.

Pin the publicly exposed metadata payload at the contract level so the
Guided Builder can rely on the same keys release-to-release. If a key the
frontend reads disappears, this test fails *before* shipping.

Add new keys freely. Removing or renaming a key requires a deliberate
frontend update.
"""

REQUIRED_TOP_KEYS = {
    "schema_version",
    "planner_modes",
    "step_types",
    "form_fields",
    "triggers",
    "policies",
    "telemetry",
    "expression_helpers",
    "tools",
}


REQUIRED_STEP_TYPE_KEYS = {
    "name",
    "label",
    "category",
    "requires_instruction",
    "requires_expect",
    "requires_description",
    "requires_params",
    "accepts_uses_credentials",
    "accepts_retry",
}


# User-facing step types the compiler accepts. `ai.fix_json` is intentionally
# excluded — the `/api/v1/flows/ai-ops` route already hides it as internal.
EXPECTED_STEP_TYPES = {
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


EXPECTED_EXPRESSION_HELPERS = {"$form", "$step", "$env", "$secret"}


def test_top_level_keys_present(app_client):
    data = app_client.get("/api/v1/flows/dsl-metadata").json()
    missing = REQUIRED_TOP_KEYS - set(data.keys())
    assert not missing, f"Missing top-level metadata keys: {sorted(missing)}"


def test_step_type_shape_is_complete(app_client):
    data = app_client.get("/api/v1/flows/dsl-metadata").json()
    types_by_name = {t["name"]: t for t in data["step_types"]}
    assert EXPECTED_STEP_TYPES <= set(
        types_by_name
    ), f"Missing step types: {sorted(EXPECTED_STEP_TYPES - set(types_by_name))}"
    for name, spec in types_by_name.items():
        missing = REQUIRED_STEP_TYPE_KEYS - set(spec.keys())
        assert not missing, f"Step type {name} missing keys: {sorted(missing)}"


def test_ai_step_types_carry_ai_op_specs(app_client):
    data = app_client.get("/api/v1/flows/dsl-metadata").json()
    for spec in data["step_types"]:
        if spec["name"].startswith("ai."):
            assert "ai_op" in spec, f"AI step {spec['name']} missing ai_op block"
            ai = spec["ai_op"]
            assert ai["output_format"] in {"json", "text"}
            assert "default_expect_schema" in ai


def test_expression_helpers_published(app_client):
    data = app_client.get("/api/v1/flows/dsl-metadata").json()
    names = {h["name"] for h in data["expression_helpers"]}
    missing = EXPECTED_EXPRESSION_HELPERS - names
    assert not missing, f"Expression helpers missing: {sorted(missing)}"
    for helper in data["expression_helpers"]:
        for key in ("syntax", "description", "needs_argument", "argument_kind"):
            assert key in helper, f"Helper {helper.get('name')} missing key {key}"


def test_planner_modes_canonical(app_client):
    data = app_client.get("/api/v1/flows/dsl-metadata").json()
    assert data["planner_modes"] == ["deterministic", "agentic"]


def test_form_field_aliases_published(app_client):
    data = app_client.get("/api/v1/flows/dsl-metadata").json()
    aliases = data["form_fields"]["aliases"]
    # The compiler accepts `regex` for `pattern` and `min`/`max` for the
    # canonical numeric bounds; the frontend relies on these being declared.
    assert "regex" in aliases["pattern"]
    assert "min" in aliases["minimum"]
    assert "max" in aliases["maximum"]
