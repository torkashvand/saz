"""Webhook reject must not clobber a run that was concurrently resumed.

The reject branch failed the run with an unguarded ``mark_failed`` while the
approve branch used the atomic ``mark_queued_if_suspended`` guard. So a reject
whose suspended-state read raced a concurrent resume/timeout would overwrite
the already-queued run with ``failed`` using a stale in-memory view.

Reproduced deterministically with the established race idiom (see
tests/integration/test_sweeper_resume_race.py): the handler session caches a
``suspended`` snapshot in its identity map, then another session commits
``queued``. The handler's guarded UPDATE must see committed state, match zero
rows, and return ``already_processed`` instead of failing the run.
"""

import asyncio

from sqlalchemy.orm import Session

from saz.api.routes.webhooks import handle_webhook_callback
from saz.api.schemas.webhook_schemas import WebhookCallbackRequest
from saz.db.models import Flow, Run, Step
from saz.db.unit_of_work import UnitOfWork
from tests.conftest import TEST_USER_ID

CALLBACK_ID = "cb_reject_race_001"


def _seed_suspended(db_engine):
    with Session(db_engine) as session:
        session.add_all(
            [
                Flow(
                    created_by_user_id=TEST_USER_ID,
                    id="flow_reject_race",
                    name="reject_race",
                    definition={"workflow": {"planner_mode": "deterministic"}},
                ),
                Run(
                    created_by_user_id=TEST_USER_ID,
                    id="run_reject_race",
                    flow_id="flow_reject_race",
                    status="suspended",
                    planner_mode="deterministic",
                    payload={},
                    error={
                        "type": "HumanApprovalRequired",
                        "step_id": "gate",
                        "callback_id": CALLBACK_ID,
                    },
                ),
                Step(
                    id="step_reject_race",
                    run_id="run_reject_race",
                    number=0,
                    name="gate",
                    step_type="human.approval",
                    status="suspended",
                    attempt=1,
                ),
            ]
        )
        session.commit()


def test_reject_after_resume_does_not_clobber_to_failed(db_engine):
    _seed_suspended(db_engine)

    handler_session = Session(db_engine)
    uow = UnitOfWork(handler_session).__enter__()
    assert uow.runs is not None
    # Cache a 'suspended' snapshot in the handler's identity map — the stale
    # view the bug relied on.
    cached = uow.runs.get("run_reject_race")
    assert cached.status == "suspended"

    # A concurrent resume commits 'queued' in another session.
    with Session(db_engine) as other:
        run = other.get(Run, "run_reject_race")
        run.status = "queued"
        run.error = {**run.error, "resolved": True}
        other.commit()

    req = WebhookCallbackRequest(action="reject", reason="too late")
    resp = asyncio.run(handle_webhook_callback(CALLBACK_ID, req, uow))
    uow.commit()
    handler_session.close()

    assert resp.status == "already_processed", resp.status
    with Session(db_engine) as session:
        run = session.get(Run, "run_reject_race")
        assert run.status == "queued", f"resumed run must not be clobbered; got {run.status!r}"


def test_normal_reject_still_fails_suspended_run(db_engine):
    _seed_suspended(db_engine)

    handler_session = Session(db_engine)
    uow = UnitOfWork(handler_session).__enter__()
    req = WebhookCallbackRequest(action="reject", reason="denied")
    resp = asyncio.run(handle_webhook_callback(CALLBACK_ID, req, uow))
    uow.commit()
    handler_session.close()

    assert resp.status == "rejected", resp.status
    with Session(db_engine) as session:
        run = session.get(Run, "run_reject_race")
        step = session.get(Step, "step_reject_race")
        assert run.status == "failed"
        assert step.status == "failed"
        assert "denied" in str(step.error)
