"""Integration tests for SuspensionSweeper.

These tests drive the sweeper synchronously via :meth:`sweep_once` so the
assertions are deterministic — the background interval scheduler is
covered separately by the lifespan smoke test in
``tests/api/test_suspension_sweeper_lifespan.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step
from saz.engine.suspension_sweeper import SuspensionSweeper
from tests.conftest import TEST_USER_ID


def _make_flow(session: Session, flow_id: str = "flow_sweeper_test") -> str:
    flow = Flow(
        created_by_user_id=TEST_USER_ID,
        id=flow_id,
        name="Sweeper Test Flow",
        definition={
            "schema_version": 1,
            "flow": {"name": flow_id, "description": "test"},
            "workflow": {
                "planner_mode": "deterministic",
                "steps": [
                    {
                        "id": "wait_step",
                        "type": "webhook.wait",
                        "description": "wait for external callback",
                        "params": {"event_name": "external"},
                    }
                ],
            },
        },
    )
    session.add(flow)
    session.commit()
    return flow_id


def _make_suspended_run(
    session: Session,
    run_id: str,
    flow_id: str,
    *,
    timeout_at: datetime,
    suspension_type: str = "WebhookWait",
    callback_id: str | None = None,
) -> str:
    run = Run(
        created_by_user_id=TEST_USER_ID,
        id=run_id,
        flow_id=flow_id,
        status="suspended",
        planner_mode="deterministic",
        payload={"foo": "bar"},
        error={
            "message": f"{suspension_type} for step wait_step",
            "type": suspension_type,
            "step_id": "wait_step",
            "callback_id": callback_id or f"cb_{run_id}",
            "suspended_at": (timeout_at - timedelta(minutes=10)).isoformat(),
            "timeout_at": timeout_at.isoformat(),
            "timeout_minutes": 10,
        },
    )
    session.add(run)
    step = Step(
        id=f"{run_id}_step",
        run_id=run_id,
        number=0,
        name="wait_step",
        step_type="webhook.wait",
        status="suspended",
    )
    session.add(step)
    session.commit()
    return run_id


def test_sweep_marks_expired_run_as_failed(db_engine):
    """A suspension whose timeout_at has passed is transitioned to
    failed with type SuspensionTimeout. The original suspension context
    (step_id, callback_id) is preserved for auditability."""
    with Session(db_engine) as session:
        flow_id = _make_flow(session)
        expired_at = datetime.now(UTC) - timedelta(minutes=1)
        run_id = _make_suspended_run(
            session,
            "run_expired_1",
            flow_id,
            timeout_at=expired_at,
            callback_id="cb_keepme",
        )

    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        interval_seconds=60.0,
        batch_limit=10,
        engine=db_engine,
    )
    count = sweeper.sweep_once()
    assert count == 1

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.error is not None
        assert run.error["type"] == "SuspensionTimeout"
        assert run.error["step_id"] == "wait_step"
        # Original suspension type retained for audit
        assert run.error["original_type"] == "WebhookWait"
        # Callback id preserved so a late callback returns already_processed,
        # not 404.
        assert run.error["callback_id"] == "cb_keepme"
        # The suspended step rolls up to failed too
        step = session.get(Step, f"{run_id}_step")
        assert step is not None
        assert step.status == "failed"


def test_sweep_leaves_runs_with_future_deadline_untouched(db_engine):
    """A suspension whose timeout_at is in the future must stay suspended."""
    with Session(db_engine) as session:
        flow_id = _make_flow(session)
        future_at = datetime.now(UTC) + timedelta(hours=1)
        run_id = _make_suspended_run(session, "run_future_1", flow_id, timeout_at=future_at)

    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        engine=db_engine,
    )
    count = sweeper.sweep_once()
    assert count == 0

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.status == "suspended"


def test_sweep_is_idempotent_for_already_failed_runs(db_engine):
    """Running the sweeper twice in a row must not transition an
    already-failed run again. The second pass is a no-op."""
    with Session(db_engine) as session:
        flow_id = _make_flow(session)
        expired_at = datetime.now(UTC) - timedelta(minutes=5)
        _make_suspended_run(session, "run_expired_2", flow_id, timeout_at=expired_at)

    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        engine=db_engine,
    )
    first = sweeper.sweep_once()
    second = sweeper.sweep_once()
    assert first == 1
    assert second == 0


def test_sweep_handles_mixed_expired_and_future(db_engine):
    """Only expired runs are timed out; future-deadline runs are not."""
    with Session(db_engine) as session:
        flow_id = _make_flow(session)
        _make_suspended_run(
            session,
            "run_mixed_expired",
            flow_id,
            timeout_at=datetime.now(UTC) - timedelta(minutes=2),
        )
        _make_suspended_run(
            session,
            "run_mixed_future",
            flow_id,
            timeout_at=datetime.now(UTC) + timedelta(minutes=10),
        )

    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        engine=db_engine,
    )
    count = sweeper.sweep_once()
    assert count == 1

    with Session(db_engine) as session:
        expired = session.get(Run, "run_mixed_expired")
        future = session.get(Run, "run_mixed_future")
        assert expired is not None and expired.status == "failed"
        assert future is not None and future.status == "suspended"


def test_sweep_emits_run_failed_event_with_suspension_timeout_type(db_engine):
    """The sweeper must emit a run.failed event so the audit timeline
    shows the timeout and the run-detail UI updates on next refetch."""
    from saz.db.models import Event as EventModel

    with Session(db_engine) as session:
        flow_id = _make_flow(session)
        _make_suspended_run(
            session,
            "run_event_check",
            flow_id,
            timeout_at=datetime.now(UTC) - timedelta(seconds=30),
        )

    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        engine=db_engine,
    )
    sweeper.sweep_once()

    with Session(db_engine) as session:
        events = list(session.query(EventModel).filter_by(run_id="run_event_check").all())
        types = [e.event_type for e in events]
        assert "run.failed" in types, f"Expected run.failed event after timeout sweep; got {types}"
        run_failed = next(e for e in events if e.event_type == "run.failed")
        assert run_failed.payload["error_type"] == "SuspensionTimeout"


def test_sweep_emits_approval_denied_for_human_approval_suspensions(db_engine):
    """Approval timeouts should emit approval.denied as well as run.failed,
    so the approval audit trail is complete."""
    from saz.db.models import Event as EventModel

    with Session(db_engine) as session:
        flow_id = _make_flow(session, flow_id="flow_approval_sweep")
        _make_suspended_run(
            session,
            "run_approval_timeout",
            flow_id,
            timeout_at=datetime.now(UTC) - timedelta(minutes=1),
            suspension_type="HumanApprovalRequired",
        )

    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        engine=db_engine,
    )
    sweeper.sweep_once()

    with Session(db_engine) as session:
        events = list(session.query(EventModel).filter_by(run_id="run_approval_timeout").all())
        types = [e.event_type for e in events]
        assert "approval.denied" in types
        assert "run.failed" in types
        # events.step_id is an FK to steps.id — the timeout event must carry
        # the real step row id, never the YAML step name ("wait_step").
        denied = next(e for e in events if e.event_type == "approval.denied")
        assert denied.step_id == "run_approval_timeout_step"


def test_fail_one_skips_run_no_longer_suspended(db_engine):
    """A run that was resumed (no longer suspended) between discovery and
    _fail_one must not be overwritten to failed."""
    from saz.db.unit_of_work import UnitOfWork

    with Session(db_engine) as session:
        flow_id = _make_flow(session, flow_id="flow_race")
        _make_suspended_run(
            session,
            "run_resumed_race",
            flow_id,
            timeout_at=datetime.now(UTC) - timedelta(minutes=1),
        )

    sweeper = SuspensionSweeper(database_url=str(db_engine.url), engine=db_engine)

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            run = session.get(Run, "run_resumed_race")
            # Simulate a callback having advanced the run already.
            run.status = "queued"
            session.flush()
            sweeper._fail_one(uow, run, datetime.now(UTC))
            uow.commit()

    with Session(db_engine) as session:
        run = session.get(Run, "run_resumed_race")
        assert run is not None
        assert run.status == "queued"


def test_sweep_respects_batch_limit(db_engine):
    """When more expired runs exist than batch_limit, only batch_limit
    are processed per pass. Subsequent passes pick up the rest."""
    with Session(db_engine) as session:
        flow_id = _make_flow(session, flow_id="flow_batch")
        for i in range(5):
            _make_suspended_run(
                session,
                f"run_batch_{i}",
                flow_id,
                timeout_at=datetime.now(UTC) - timedelta(seconds=30 + i),
            )

    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        batch_limit=2,
        engine=db_engine,
    )
    first = sweeper.sweep_once()
    second = sweeper.sweep_once()
    third = sweeper.sweep_once()
    assert first == 2
    assert second == 2
    assert third == 1


def test_sweep_writes_step_error_as_dict_for_run_detail_api(app_client, db_engine):
    """Regression: ``SuspensionSweeper._fail_one`` used to set
    ``Step.error = error["message"]`` (a bare string). The audit pipeline
    — ``categorize_error`` / ``enrich_step_with_failure_reason`` — calls
    ``error.get("type")`` on that field, so the run-detail API would 500
    once a sweeper-reaped run existed. The step error must therefore be a
    dict carrying at least ``message`` and ``type``."""
    with Session(db_engine) as session:
        flow_id = _make_flow(session, flow_id="flow_step_error_dict")
        run_id = _make_suspended_run(
            session,
            "run_step_error_dict",
            flow_id,
            timeout_at=datetime.now(UTC) - timedelta(minutes=1),
        )

    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        engine=db_engine,
    )
    assert sweeper.sweep_once() == 1

    # 1. The DB column itself must be a dict, not a string.
    with Session(db_engine) as session:
        step = session.get(Step, f"{run_id}_step")
        assert step is not None
        assert step.status == "failed"
        assert isinstance(step.error, dict), (
            f"Step.error must be a dict so the audit pipeline can read "
            f".get('type') on it; got {type(step.error).__name__}: {step.error!r}"
        )
        assert step.error["type"] == "SuspensionTimeout"
        assert "Suspension timed out" in step.error["message"]

    # 2. The full run-detail API path must serialize the run without
    #    exploding — this is the consumer path that previously crashed
    #    on the string error via ``error.get('type')``.
    response = app_client.get(f"/api/v1/runs/{run_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "failed"
    # Locate the timed-out step in the response and confirm the shape
    # downstream code expects.
    steps = body.get("steps", [])
    timed_out_steps = [s for s in steps if s.get("status") == "failed"]
    assert timed_out_steps, "expected the timed-out step in the API response"
    api_error = timed_out_steps[0].get("error")
    assert isinstance(
        api_error, dict
    ), f"Run-detail step.error must serialize as an object; got {api_error!r}"
    assert api_error.get("type") == "SuspensionTimeout"


def test_late_webhook_callback_after_timeout_returns_already_processed(app_client, db_engine):
    """A late callback to a timed-out run must not 404, because the
    callback_id is preserved in the failed-run error payload."""
    with Session(db_engine) as session:
        flow_id = _make_flow(session, flow_id="flow_late_callback")
        _make_suspended_run(
            session,
            "run_late_callback",
            flow_id,
            timeout_at=datetime.now(UTC) - timedelta(minutes=1),
            callback_id="cb_late_lookup",
        )

    sweeper = SuspensionSweeper(
        database_url=str(db_engine.url),
        engine=db_engine,
    )
    sweeper.sweep_once()

    # A late callback finds the (now-failed) run by its preserved
    # callback_id; the endpoint must respond with already_processed
    # because the run is no longer suspended.
    response = app_client.post(
        "/api/v1/webhooks/callback/cb_late_lookup",
        json={"action": "approve"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "already_processed"
    assert body["run_id"] == "run_late_callback"
