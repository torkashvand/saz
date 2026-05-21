"""PUT /api/v1/flows/{id} updates by ID, so renames don't fork the row."""

from __future__ import annotations

import textwrap


def _yaml(name: str = "demo_flow", description: str = "demo desc") -> str:
    return textwrap.dedent(
        f"""\
        schema_version: 1
        flow:
          name: {name}
          version: "1.0"
          description: "{description}"
        workflow:
          planner_mode: deterministic
          steps:
            - id: classify
              type: ai.extract
              description: classify
              instruction: do
              expect:
                type: object
                properties:
                  ok:
                    type: boolean
                required: [ok]
        """
    )


def test_put_flow_updates_existing_row_by_id(app_client):
    """A successful update should keep the same row id even when the name changes."""

    created = app_client.post("/api/v1/flows", json={"yaml": _yaml(name="initial")}).json()
    flow_id = created["id"]

    response = app_client.put(
        f"/api/v1/flows/{flow_id}",
        json={"yaml": _yaml(name="renamed_flow", description="updated")},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["id"] == flow_id
    assert updated["name"] == "renamed_flow"

    # GET still returns the same row with the new name.
    detail = app_client.get(f"/api/v1/flows/{flow_id}").json()
    assert detail["name"] == "renamed_flow"


def test_put_flow_404_when_id_missing(app_client):
    response = app_client.put(
        "/api/v1/flows/does-not-exist",
        json={"yaml": _yaml(name="x")},
    )
    assert response.status_code == 404


def test_put_flow_rejects_invalid_yaml(app_client):
    created = app_client.post("/api/v1/flows", json={"yaml": _yaml(name="will_keep")}).json()
    flow_id = created["id"]

    bad_yaml = "flow:\n  name: bad\n# missing workflow + schema_version\n"
    response = app_client.put(f"/api/v1/flows/{flow_id}", json={"yaml": bad_yaml})
    assert response.status_code == 400

    # Original row must be untouched.
    detail = app_client.get(f"/api/v1/flows/{flow_id}").json()
    assert detail["name"] == "will_keep"
