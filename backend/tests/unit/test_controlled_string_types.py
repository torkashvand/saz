"""Regression tests proving controlled string types reject invalid values.

Before these types were introduced, fields like ``WebhookCallbackRequest.action``
and ``RunListItem.status`` were typed as plain ``str`` with the allowed values
documented only in comments — drift was silent and never caught at the
boundary. These tests pin that contract: invalid values must be rejected,
and StrEnum-typed fields must coerce wire-format strings without changing
JSON output.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from saz.api.schemas.event_schemas import EventResponse, RunSummaryResponse
from saz.api.schemas.flow_schemas import FlowDetail, WorkflowPolicies
from saz.api.schemas.run_schemas import (
    CreateRunResponse,
    RunDetailResponse,
    StepSummary,
)
from saz.api.schemas.webhook_schemas import (
    WebhookCallbackRequest,
    WebhookCallbackResponse,
    WebhookResponse,
)
from saz.domain.literals import (
    Actor,
    PlannerMode,
    RunStatus,
    Severity,
    StepStatus,
)

# ---------------------------------------------------------------------------
# Webhook callback action/status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_webhook_callback_request_accepts_valid_action(action):
    req = WebhookCallbackRequest(action=action)
    assert req.action == action


@pytest.mark.parametrize("bad", ["maybe", "APPROVE", "approved", ""])
def test_webhook_callback_request_rejects_invalid_action(bad):
    with pytest.raises(ValidationError):
        WebhookCallbackRequest(action=bad)


@pytest.mark.parametrize("status", ["resumed", "rejected", "already_processed"])
def test_webhook_callback_response_accepts_valid_status(status):
    resp = WebhookCallbackResponse(status=status, run_id="r1", message="ok")
    assert resp.status == status


def test_webhook_callback_response_rejects_invalid_status():
    with pytest.raises(ValidationError):
        WebhookCallbackResponse(status="bogus", run_id="r1", message="ok")


def test_webhook_response_status_locked_to_received():
    resp = WebhookResponse(message="ok")
    assert resp.status == "received"
    with pytest.raises(ValidationError):
        WebhookResponse(status="other", message="ok")


# ---------------------------------------------------------------------------
# Run / Step status on API responses
# ---------------------------------------------------------------------------


def test_create_run_response_rejects_invalid_status():
    CreateRunResponse(id="r1", flow_id="f1", status="queued")
    with pytest.raises(ValidationError):
        CreateRunResponse(id="r1", flow_id="f1", status="not_a_status")


def test_run_detail_response_serializes_strenum_as_plain_string():
    payload = RunDetailResponse(
        id="r1",
        flow_id="f1",
        flow_name="n",
        status=RunStatus.RUNNING,
        planner_mode=PlannerMode.AGENTIC,
        payload={},
        created_at=datetime(2026, 1, 1),
        total_tokens=0,
        total_cost_usd=0.0,
        steps=[],
    )
    dumped = payload.model_dump(mode="json")
    assert dumped["status"] == "running"
    assert dumped["planner_mode"] == "agentic"


def test_run_detail_response_rejects_unknown_planner_mode():
    with pytest.raises(ValidationError):
        RunDetailResponse(
            id="r1",
            flow_id="f1",
            flow_name="n",
            status="queued",
            planner_mode="hybrid",
            payload={},
            created_at=datetime(2026, 1, 1),
            total_tokens=0,
            total_cost_usd=0.0,
            steps=[],
        )


def test_step_summary_rejects_invalid_status():
    StepSummary(id="s1", number=1, name="x", step_type="tool.call", status="completed")
    with pytest.raises(ValidationError):
        StepSummary(id="s1", number=1, name="x", step_type="tool.call", status="halfway")


# ---------------------------------------------------------------------------
# Flow planner_mode
# ---------------------------------------------------------------------------


def test_flow_detail_rejects_unknown_planner_mode():
    policies = WorkflowPolicies(max_steps=10, max_cost_usd=1.0, max_tokens=1000)
    FlowDetail(
        id="f1",
        name="n",
        definition={},
        planner_mode="deterministic",
        policies=policies,
        step_count=0,
        created_at=datetime(2026, 1, 1),
    )
    with pytest.raises(ValidationError):
        FlowDetail(
            id="f1",
            name="n",
            definition={},
            planner_mode="ai_planner",
            policies=policies,
            step_count=0,
            created_at=datetime(2026, 1, 1),
        )


# ---------------------------------------------------------------------------
# Event response severity / actor
# ---------------------------------------------------------------------------


def _event_kwargs(**overrides):
    base = dict(
        id="evt-1",
        event_type="run.started",
        timestamp=datetime(2026, 1, 1),
        schema_version=1,
        run_id="r1",
        planner_mode="deterministic",
        severity="info",
        actor="system",
        summary="started",
        payload={},
        tags={},
    )
    base.update(overrides)
    return base


def test_event_response_rejects_invalid_severity():
    EventResponse(**_event_kwargs())
    with pytest.raises(ValidationError):
        EventResponse(**_event_kwargs(severity="critical"))


def test_event_response_rejects_invalid_actor():
    with pytest.raises(ValidationError):
        EventResponse(**_event_kwargs(actor="robot"))


def test_run_summary_response_rejects_invalid_status_and_mode():
    RunSummaryResponse(
        id="r1",
        flow_id="f1",
        status="completed",
        planner_mode="deterministic",
        created_at=datetime(2026, 1, 1),
    )
    with pytest.raises(ValidationError):
        RunSummaryResponse(
            id="r1",
            flow_id="f1",
            status="halfway",
            planner_mode="deterministic",
            created_at=datetime(2026, 1, 1),
        )
    with pytest.raises(ValidationError):
        RunSummaryResponse(
            id="r1",
            flow_id="f1",
            status="completed",
            planner_mode="manual",
            created_at=datetime(2026, 1, 1),
        )


# ---------------------------------------------------------------------------
# StrEnum membership — guards against accidental enum-member removal that
# would silently break Pydantic coercion of historical DB rows.
# ---------------------------------------------------------------------------


def test_run_status_covers_full_lifecycle():
    """``failed`` is the single terminal-failure state; no production
    writer produces ``"error"``."""
    assert {s.value for s in RunStatus} == {
        "queued",
        "running",
        "suspended",
        "failed",
        "completed",
    }


def test_step_status_members():
    assert {s.value for s in StepStatus} == {
        "queued",
        "running",
        "suspended",
        "failed",
        "completed",
    }


def test_planner_mode_members():
    assert {m.value for m in PlannerMode} == {"deterministic", "agentic"}


def test_severity_members():
    assert {s.value for s in Severity} == {"info", "warn", "error"}


def test_actor_members():
    assert {a.value for a in Actor} == {"system", "user", "llm"}
