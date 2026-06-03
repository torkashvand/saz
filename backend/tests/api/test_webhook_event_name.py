"""webhook.wait callbacks are validated against the awaited event name.

A callback that names a different event than the one the webhook.wait step
declared is rejected; a matching (or omitted) event name resumes the run.
"""

from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step
from tests.conftest import TEST_USER_ID

CB_ID = "cb_event_name_test_001"


def _seed_webhook_wait(db_engine, event_name="payment_settled"):
    with Session(db_engine) as session:
        session.add(
            Flow(
                created_by_user_id=TEST_USER_ID,
                id="flow_evt",
                name="Webhook Wait Flow",
                definition={"workflow": {"planner_mode": "deterministic"}},
            )
        )
        session.add(
            Run(
                created_by_user_id=TEST_USER_ID,
                id="run_evt",
                flow_id="flow_evt",
                status="suspended",
                planner_mode="deterministic",
                payload={},
                error={
                    "type": "WebhookWait",
                    "step_id": "wait",
                    "callback_id": CB_ID,
                    "event_name": event_name,
                },
            )
        )
        session.add(
            Step(
                id="step_evt",
                run_id="run_evt",
                number=0,
                name="wait",
                step_type="webhook.wait",
                status="suspended",
                attempt=1,
            )
        )
        session.commit()


def test_mismatched_event_name_rejected(app_client, db_engine):
    _seed_webhook_wait(db_engine)
    resp = app_client.post(
        f"/api/v1/webhooks/callback/{CB_ID}",
        json={"action": "approve", "event_name": "wrong_event"},
    )
    assert resp.status_code == 400, resp.text
    with Session(db_engine) as session:
        assert session.get(Run, "run_evt").status == "suspended"


def test_matching_event_name_resumes(app_client, db_engine):
    _seed_webhook_wait(db_engine)
    resp = app_client.post(
        f"/api/v1/webhooks/callback/{CB_ID}",
        json={"action": "approve", "event_name": "payment_settled"},
    )
    assert resp.status_code == 200, resp.text
    with Session(db_engine) as session:
        assert session.get(Run, "run_evt").status != "suspended"


def test_omitted_event_name_still_resumes(app_client, db_engine):
    _seed_webhook_wait(db_engine)
    resp = app_client.post(
        f"/api/v1/webhooks/callback/{CB_ID}",
        json={"action": "approve"},
    )
    assert resp.status_code == 200, resp.text
