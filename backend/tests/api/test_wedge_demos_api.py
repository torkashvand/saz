"""API-level tests for the three wedge demos.

Covers the operator-facing discovery + registration paths:
  * GET  /api/templates/                  — wedge demos surface as recommended
  * GET  /api/templates/{id}              — wedge demo YAML is readable
  * POST /api/v1/flows/compile            — wedge demo compiles via the API
  * POST /api/v1/flows                    — wedge demo can be registered as a flow

End-to-end suspend/resume + callback semantics live in
`tests/api/test_webhook_callback_api.py` and
`tests/integration/test_approval_workflow.py`.
"""

from __future__ import annotations

import pytest

WEDGE_DEMO_IDS = (
    "incident_triage",
    "change_approval_ansible",
    "callback_driven_maintenance",
)


def test_templates_endpoint_lists_wedge_demos(app_client):
    """GET /api/templates/ must return the three wedge demos with the
    'wedge-demo' tag and recommended=true."""
    response = app_client.get("/api/templates/")
    assert response.status_code == 200
    by_id = {t["id"]: t for t in response.json()}
    for demo_id in WEDGE_DEMO_IDS:
        assert demo_id in by_id, f"Templates endpoint must surface {demo_id}; got {list(by_id)}"
        entry = by_id[demo_id]
        assert (
            entry["recommended"] is True
        ), f"{demo_id} should be marked recommended=true at the API layer"
        assert (
            "wedge-demo" in entry["tags"]
        ), f"{demo_id} should carry 'wedge-demo' tag in the API response"


def test_templates_endpoint_recommended_only_filter_includes_wedges(app_client):
    """The recommended_only filter must return all three wedge demos."""
    response = app_client.get("/api/templates/?recommended_only=true")
    assert response.status_code == 200
    ids = {t["id"] for t in response.json()}
    for demo_id in WEDGE_DEMO_IDS:
        assert demo_id in ids, f"Recommended-only listing should include {demo_id}"


@pytest.mark.parametrize("demo_id", WEDGE_DEMO_IDS)
def test_template_detail_yaml_returned(app_client, demo_id):
    """GET /api/templates/{id} must return YAML the operator can pipe back
    into the flow registration endpoint."""
    response = app_client.get(f"/api/templates/{demo_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["id"] == demo_id
    yaml_text = payload["yaml"]
    assert (
        isinstance(yaml_text, str) and yaml_text.strip()
    ), f"{demo_id} detail must include non-empty yaml content"
    # The yaml field is the meta-stripped definition that should round-trip
    # through the compile endpoint without errors.
    compile_resp = app_client.post(
        "/api/v1/flows/compile",
        json={"yaml": yaml_text},
    )
    assert (
        compile_resp.status_code == 200
    ), f"{demo_id} template YAML must compile via /api/v1/flows/compile"
    summary = compile_resp.json()
    assert summary["flow_name"] == demo_id
    assert (
        summary["warnings"] == []
    ), f"{demo_id} must compile with no warnings; got {summary['warnings']}"


@pytest.mark.parametrize("demo_id", WEDGE_DEMO_IDS)
def test_wedge_demo_registers_as_flow(app_client, demo_id):
    """The wedge demos must register cleanly through the same endpoint
    operators use (POST /api/v1/flows). This guards against silent
    regressions in the registration path that would still let the YAML
    compile in isolation."""
    detail = app_client.get(f"/api/templates/{demo_id}").json()
    yaml_text = detail["yaml"]

    register = app_client.post(
        "/api/v1/flows",
        json={"yaml": yaml_text},
    )
    assert register.status_code == 200, f"Flow registration failed for {demo_id}: {register.text}"
    body = register.json()
    assert body["name"] == demo_id


def test_change_approval_demo_exposes_two_ansible_steps_via_compile(app_client):
    """The change-approval wedge must report exactly the steps the demo
    relies on through the public compile API — so an operator inspecting
    the API can see the check + approval + apply pattern before running."""
    detail = app_client.get("/api/templates/change_approval_ansible").json()
    compile_resp = app_client.post(
        "/api/v1/flows/compile",
        json={"yaml": detail["yaml"]},
    )
    assert compile_resp.status_code == 200
    summary = compile_resp.json()["workflow_summary"]
    # Two Ansible tool calls + one approval + summary steps + two artifact
    # stores: at least 6 steps total. The exact list is asserted in
    # tests/examples/test_wedge_demos.py.
    assert summary["steps_count"] >= 6


def test_callback_demo_exposes_webhook_wait_via_compile(app_client):
    """The callback-driven wedge must include exactly one webhook.wait step
    visible through the operator-facing compile endpoint."""
    detail = app_client.get("/api/templates/callback_driven_maintenance").json()
    compile_resp = app_client.post(
        "/api/v1/flows/compile",
        json={"yaml": detail["yaml"]},
    )
    assert compile_resp.status_code == 200
    # The compile summary doesn't expose step types; assert that the
    # registered flow definition contains a webhook.wait step.
    register = app_client.post("/api/v1/flows", json={"yaml": detail["yaml"]})
    assert register.status_code == 200
    flow_id = register.json()["id"]

    flow_detail = app_client.get(f"/api/v1/flows/{flow_id}").json()
    step_types = [s.get("type") for s in flow_detail["definition"]["workflow"]["steps"]]
    assert step_types.count("webhook.wait") == 1, (
        f"callback_driven_maintenance must register with exactly one "
        f"webhook.wait step; got {step_types}"
    )
