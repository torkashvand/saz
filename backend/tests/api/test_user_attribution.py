"""Verify that important actions are attributed to the authenticated user."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from saz.db.models import Credential, Event, Flow, Run, Step
from tests.conftest import TEST_USER_ID

FLOW_YAML = """
schema_version: 1
flow:
  name: Attribution Test Flow
  description: Minimal flow used to verify user attribution on register/run/retry.
workflow:
  planner_mode: deterministic
  steps:
    - id: noop
      type: tool.call
      description: Call a stub HTTP endpoint
      tool: http_request
      params:
        method: GET
        url: https://example.com
"""


def test_register_flow_records_creator(app_client, db_engine):
    resp = app_client.post("/api/v1/flows", json={"yaml": FLOW_YAML})
    assert resp.status_code == 200, resp.text
    flow_id = resp.json()["id"]
    with Session(db_engine) as s:
        flow = s.get(Flow, flow_id)
        assert flow is not None
        assert flow.created_by_user_id == TEST_USER_ID


def test_create_run_records_creator(app_client, db_engine):
    reg = app_client.post("/api/v1/flows", json={"yaml": FLOW_YAML})
    flow_id = reg.json()["id"]
    resp = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["id"]
    with Session(db_engine) as s:
        run = s.get(Run, run_id)
        assert run is not None
        assert run.created_by_user_id == TEST_USER_ID
        # triggered_by metadata also carries the user
        assert run.triggered_by is not None
        assert run.triggered_by.get("user_id") == TEST_USER_ID


def test_create_credential_records_creator(app_client, db_engine):
    resp = app_client.post(
        "/api/v1/credentials",
        json={"name": "cred_attrib_1", "type": "api_token", "data": {"token": "x"}},
    )
    assert resp.status_code == 200, resp.text
    with Session(db_engine) as s:
        cred = s.get(Credential, "cred_attrib_1")
        assert cred is not None
        assert cred.created_by_user_id == TEST_USER_ID


def test_retry_emits_user_attributed_event(app_client, db_engine):
    """POST /retry must emit a user-actor event carrying actor_user_id.

    We seed Flow + Run + Step directly so the scheduler never picks the
    run up. Going through POST /runs would start a real execution loop
    that races with our synthetic "this run failed" state, with the
    executor's own attempts overwriting our injected step rows.
    """
    flow_id = "flow_attribution_retry"
    run_id = "run_attribution_retry"
    with Session(db_engine) as s:
        s.add(
            Flow(
                id=flow_id,
                name="Attribution Retry Flow",
                definition={"workflow": {"planner_mode": "deterministic"}},
                created_at=datetime.now(UTC),
                created_by_user_id=TEST_USER_ID,
            )
        )
        s.add(
            Run(
                id=run_id,
                flow_id=flow_id,
                status="failed",
                planner_mode="deterministic",
                payload={},
                error={"message": "induced"},
                created_at=datetime.now(UTC),
                created_by_user_id=TEST_USER_ID,
            )
        )
        s.add(
            Step(
                id="step-failed-1",
                run_id=run_id,
                number=1,
                name="noop",
                attempt=1,
                status="failed",
                step_type="tool.call",
                error={"message": "boom"},
            )
        )
        s.commit()

    resp = app_client.post(f"/api/v1/runs/{run_id}/retry")
    assert resp.status_code == 200, resp.text

    with Session(db_engine) as s:
        events = (
            s.execute(select(Event).where(Event.run_id == run_id, Event.actor == "user"))
            .scalars()
            .all()
        )
        # At least the retry "run.resumed (by user)" event should exist.
        assert events, "expected at least one user-actor event after retry"
        assert all(
            e.actor_user_id == TEST_USER_ID for e in events
        ), "user-actor events must carry actor_user_id"
