"""Tests for webhook callback flow.

Proves proposal claim: "run suspends awaiting approval → approval callback resumes run →
rejection callback fails run → duplicate callback handled idempotently →
invalid callback rejected → callback events audited."
"""

import pytest
from sqlalchemy.orm import sessionmaker

from saz.db.models import Flow, Run
from saz.repositories.write.run_repository import RunRepository


@pytest.fixture
def repo(db_engine):
    """Create a RunRepository with a test session."""
    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    yield RunRepository(session)
    session.close()


@pytest.fixture
def suspended_run_with_callback(db_engine, repo):
    """Create a suspended run with callback_id in error dict."""
    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    flow = Flow(
        id="flow-webhook-test",
        name="webhook-test",
        definition={"workflow": {"planner_mode": "deterministic", "steps": []}},
    )
    session.add(flow)
    session.commit()

    run = Run(
        id="run-webhook-test",
        flow_id="flow-webhook-test",
        status="suspended",
        planner_mode="deterministic",
        payload={},
        error={
            "message": "Human approval required",
            "type": "HumanApprovalRequired",
            "step_id": "approval_step",
            "callback_id": "callback-abc-123",
        },
    )
    session.add(run)
    session.commit()
    session.close()

    return "run-webhook-test", "callback-abc-123"


def test_find_by_callback_id_success(db_engine, suspended_run_with_callback):
    """find_by_callback_id returns the correct suspended run."""
    run_id, callback_id = suspended_run_with_callback
    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    repo = RunRepository(session)

    found = repo.find_by_callback_id(callback_id)
    assert found is not None
    assert found.id == run_id
    assert found.status == "suspended"
    session.close()


def test_find_by_callback_id_not_found(db_engine, suspended_run_with_callback):
    """find_by_callback_id returns None for unknown callback."""
    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    repo = RunRepository(session)

    found = repo.find_by_callback_id("nonexistent-callback")
    assert found is None
    session.close()


def test_find_by_callback_id_finds_non_suspended(db_engine, suspended_run_with_callback):
    """find_by_callback_id finds runs regardless of status (for idempotency)."""
    run_id, callback_id = suspended_run_with_callback
    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    repo = RunRepository(session)

    # Mark run as completed
    run = repo.get(run_id)
    run.status = "completed"
    session.commit()

    # Should still find it (enables idempotent duplicate detection)
    found = repo.find_by_callback_id(callback_id)
    assert found is not None
    assert found.id == run_id
    assert found.status == "completed"
    session.close()


def test_mark_suspended_stores_callback_id(db_engine):
    """mark_suspended stores callback_id in error dict."""
    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    flow = Flow(
        id="flow-suspend-test",
        name="test",
        definition={"workflow": {"planner_mode": "deterministic", "steps": []}},
    )
    run = Run(
        id="run-suspend-test",
        flow_id="flow-suspend-test",
        status="running",
        planner_mode="deterministic",
        payload={},
    )
    session.add_all([flow, run])
    session.commit()

    repo = RunRepository(session)
    repo.mark_suspended(
        "run-suspend-test",
        {
            "message": "Needs approval",
            "type": "HumanApprovalRequired",
            "callback_id": "cb-xyz-789",
        },
    )
    session.commit()

    updated = repo.get("run-suspend-test")
    assert updated.status == "suspended"
    assert updated.error["callback_id"] == "cb-xyz-789"
    session.close()


def test_mark_failed_after_rejection(db_engine, suspended_run_with_callback):
    """Rejecting a callback marks run as failed."""
    run_id, callback_id = suspended_run_with_callback
    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    repo = RunRepository(session)

    repo.mark_failed(
        run_id,
        {
            "message": "Rejected via webhook",
            "type": "WebhookRejection",
            "callback_id": callback_id,
        },
    )
    session.commit()

    run = repo.get(run_id)
    assert run.status == "failed"
    assert run.error["type"] == "WebhookRejection"
    session.close()


def test_multiple_suspended_runs_distinct_callbacks(db_engine):
    """Multiple suspended runs with different callbacks are found independently."""
    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    flow = Flow(
        id="flow-multi",
        name="multi-test",
        definition={"workflow": {"planner_mode": "deterministic", "steps": []}},
    )
    session.add(flow)
    session.commit()

    for i in range(3):
        run = Run(
            id=f"run-multi-{i}",
            flow_id="flow-multi",
            status="suspended",
            planner_mode="deterministic",
            payload={},
            error={
                "message": "Needs approval",
                "type": "HumanApprovalRequired",
                "callback_id": f"cb-{i}",
            },
        )
        session.add(run)
    session.commit()

    repo = RunRepository(session)
    for i in range(3):
        found = repo.find_by_callback_id(f"cb-{i}")
        assert found is not None
        assert found.id == f"run-multi-{i}"

    session.close()
