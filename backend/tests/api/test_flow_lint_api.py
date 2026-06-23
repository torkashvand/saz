"""API tests: /flows/lint preview and the registration gate (422 + findings)."""

CLEAN_YAML = """
schema_version: 1
flow:
  name: lint_api_clean
  description: clean flow
workflow:
  planner_mode: deterministic
  steps:
    - id: summarize
      type: ai.extract
      instruction: |
        - "pre_checks" must list EXACTLY 3 to 6 items.
      expect:
        type: object
        properties:
          pre_checks:
            type: array
            items: { type: string }
            minItems: 3
            maxItems: 6
        required: [pre_checks]
"""

COUNT_MISMATCH_YAML = """
schema_version: 1
flow:
  name: lint_api_bad
  description: count mismatch
workflow:
  planner_mode: deterministic
  steps:
    - id: summarize
      type: ai.extract
      instruction: |
        - "pre_checks" is a short ordered list (3-6 items) to verify.
      expect:
        type: object
        properties:
          pre_checks:
            type: array
            items: { type: string }
            minItems: 1
        required: [pre_checks]
"""


def test_lint_endpoint_clean(app_client):
    resp = app_client.post("/api/v1/flows/lint", json={"yaml": CLEAN_YAML})
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["findings"] == []
    assert data["llm_ran"] is False


def test_lint_endpoint_reports_findings_without_persisting(app_client):
    resp = app_client.post("/api/v1/flows/lint", json={"yaml": COUNT_MISMATCH_YAML})
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    codes = {f["code"] for f in data["findings"]}
    assert "PROSE_SCHEMA_COUNT_MISMATCH" in codes
    # not persisted
    listing = app_client.get("/api/v1/flows").json()
    names = {f["name"] for f in listing["items"]}
    assert "lint_api_bad" not in names


def test_lint_endpoint_compile_error(app_client):
    resp = app_client.post("/api/v1/flows/lint", json={"yaml": "not: a: valid: flow"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert data["compile_error"]


def test_register_blocked_returns_422_with_findings(app_client):
    resp = app_client.post("/api/v1/flows", json={"yaml": COUNT_MISMATCH_YAML})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "flow_lint_error"
    codes = {f["code"] for f in body["findings"]}
    assert "PROSE_SCHEMA_COUNT_MISMATCH" in codes


def test_register_clean_succeeds(app_client):
    resp = app_client.post("/api/v1/flows", json={"yaml": CLEAN_YAML})
    assert resp.status_code == 200
    assert resp.json()["name"] == "lint_api_clean"
