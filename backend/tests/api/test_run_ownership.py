"""REST run endpoints enforce per-run ownership (parity with the WS stream).

A non-admin user may only read/act on their own runs; another user's runs are
forbidden (403) and excluded from listings.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, User
from saz.security import hash_password
from tests.conftest import TEST_USER_ID

OTHER_USER_ID = "00000000-0000-0000-0000-0000000000ff"


def _seed_other_users_run(db_engine, run_id="run_other"):
    with Session(db_engine) as session:
        if session.get(User, OTHER_USER_ID) is None:
            now = datetime.now(UTC)
            session.add(
                User(
                    id=OTHER_USER_ID,
                    username="other",
                    email="other@example.com",
                    password_hash=hash_password("x"),
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )
        if session.get(Flow, "flow_other") is None:
            session.add(
                Flow(
                    created_by_user_id=OTHER_USER_ID,
                    id="flow_other",
                    name="Other Flow",
                    definition={"workflow": {"planner_mode": "deterministic"}},
                )
            )
        session.add(
            Run(
                created_by_user_id=OTHER_USER_ID,
                id=run_id,
                flow_id="flow_other",
                status="completed",
                planner_mode="deterministic",
                payload={},
            )
        )
        session.commit()
    return run_id


def test_get_run_detail_other_owner_forbidden(app_client, db_engine):
    _seed_other_users_run(db_engine)
    resp = app_client.get("/api/v1/runs/run_other")
    assert resp.status_code == 403, resp.text


def test_get_run_events_other_owner_forbidden(app_client, db_engine):
    _seed_other_users_run(db_engine)
    resp = app_client.get("/api/v1/runs/run_other/events")
    assert resp.status_code == 403, resp.text


def test_get_run_steps_other_owner_forbidden(app_client, db_engine):
    _seed_other_users_run(db_engine)
    resp = app_client.get("/api/v1/runs/run_other/steps")
    assert resp.status_code == 403, resp.text


def test_list_runs_excludes_other_owners(app_client, db_engine):
    _seed_other_users_run(db_engine, run_id="run_other_listed")
    # Seed a run owned by the authenticated test user.
    with Session(db_engine) as session:
        session.add(
            Flow(
                created_by_user_id=TEST_USER_ID,
                id="flow_mine",
                name="Mine",
                definition={"workflow": {"planner_mode": "deterministic"}},
            )
        )
        session.add(
            Run(
                created_by_user_id=TEST_USER_ID,
                id="run_mine",
                flow_id="flow_mine",
                status="completed",
                planner_mode="deterministic",
                payload={},
            )
        )
        session.commit()

    resp = app_client.get("/api/v1/runs")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert "run_mine" in ids
    assert "run_other_listed" not in ids


def test_owner_can_read_own_run(app_client, db_engine):
    with Session(db_engine) as session:
        session.add(
            Flow(
                created_by_user_id=TEST_USER_ID,
                id="flow_self",
                name="Self",
                definition={"workflow": {"planner_mode": "deterministic"}},
            )
        )
        session.add(
            Run(
                created_by_user_id=TEST_USER_ID,
                id="run_self",
                flow_id="flow_self",
                status="completed",
                planner_mode="deterministic",
                payload={},
            )
        )
        session.commit()
    resp = app_client.get("/api/v1/runs/run_self")
    assert resp.status_code == 200, resp.text
