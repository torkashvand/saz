"""Flow registration validation — POST /api/v1/flows must agree with /compile.

Bug being pinned: FlowService.register() only does yaml.safe_load() and never
calls compile_dsl(), so invalid workflows that /api/v1/flows/compile rejects can
still be registered and persisted, with failures pushed to runtime instead of
register time.
"""

import pytest

VALID_DETERMINISTIC_FLOW = """
schema_version: 1
flow:
  name: valid_flow_for_baseline
  description: Baseline so we know the route works for good input
workflow:
  planner_mode: deterministic
  steps:
    - id: extract
      type: ai.extract
      instruction: Extract data from input
      expect:
        properties:
          field:
            type: string
        required: [field]
"""


AI_FLOW_MISSING_EXPECT = """
schema_version: 1
flow:
  name: invalid_ai_missing_expect
  description: ai.extract step without required `expect` schema
workflow:
  planner_mode: deterministic
  steps:
    - id: extract
      type: ai.extract
      instruction: Extract data from input
"""


FLOW_WITH_UNKNOWN_STEP_TYPE = """
schema_version: 1
flow:
  name: invalid_unknown_step
  description: Workflow with a step type that does not exist
workflow:
  planner_mode: deterministic
  steps:
    - id: do_something
      type: definitely.not.a.real.step.type
      description: bogus step
"""


FLOW_WITH_BROKEN_TEMPLATE = """
schema_version: 1
flow:
  name: invalid_template_ref
  description: Workflow referencing a non-existent prior step in template
workflow:
  planner_mode: deterministic
  steps:
    - id: use_missing
      type: tool.call
      description: References a step that was never declared
      tool: http_request
      params:
        url: "https://example.com/{{ $step('does_not_exist').field }}"
"""


def test_register_accepts_valid_flow(app_client):
    response = app_client.post(
        "/api/v1/flows",
        json={"yaml": VALID_DETERMINISTIC_FLOW},
    )
    assert response.status_code == 200, response.text


def test_compile_endpoint_rejects_ai_step_without_expect(app_client):
    """Baseline: /compile catches the bug, so /register should too.

    /compile is a validator endpoint — it returns 200 with valid=false +
    structured errors on bad DSL rather than raising 400. Register still
    rejects with 400 because saving bad DSL would be destructive.
    """
    response = app_client.post(
        "/api/v1/flows/compile",
        json={"yaml": AI_FLOW_MISSING_EXPECT},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid"] is False, (
        "Compile must reject ai.extract without expect — if this asserts, the "
        "bug moved and the rest of this file no longer pins what it claims to."
    )
    assert body["errors"], "expected structured errors on rejection"


@pytest.mark.parametrize(
    "yaml_doc, label",
    [
        (AI_FLOW_MISSING_EXPECT, "ai_step_without_expect"),
        (FLOW_WITH_UNKNOWN_STEP_TYPE, "unknown_step_type"),
        (FLOW_WITH_BROKEN_TEMPLATE, "broken_template_reference"),
    ],
)
def test_register_rejects_what_compile_rejects(app_client, yaml_doc, label):
    """POST /api/v1/flows must reject the same DSL that /compile rejects.

    Today it does not — yaml.safe_load + a name check is the only validation,
    so workflows that would crash the executor get persisted to the DB and
    fail later. This test fails until register() runs through compile_dsl().
    """
    compile_resp = app_client.post(
        "/api/v1/flows/compile",
        json={"yaml": yaml_doc},
    )
    assert compile_resp.status_code == 200, (
        f"Compile must return 200 with valid=false for {label}; " f"got {compile_resp.status_code}"
    )
    assert compile_resp.json()["valid"] is False, (
        f"Compile must reject {label} for this test to be meaningful; " f"got valid=true"
    )

    register_resp = app_client.post(
        "/api/v1/flows",
        json={"yaml": yaml_doc},
    )
    assert register_resp.status_code >= 400, (
        f"Register must reject {label} as well — compile rejects it but "
        f"register returned {register_resp.status_code}. Invalid flow "
        f"definitions should not be persisted."
    )
