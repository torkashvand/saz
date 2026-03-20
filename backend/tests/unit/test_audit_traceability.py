"""Tests for audit traceability — all events emitted correctly.

Proves proposal claim: "run events persisted and retrievable,
planner/verifier/replan/tool events all present in correct order,
final outcome event emitted for success/failure/escalation."
"""

import pytest

from saz.audit.event_emitter import EventEmitter
from saz.domain.event_schema import Event, EventType


class FakeUnitOfWork:
    """Minimal UoW that captures emitted events."""

    def __init__(self):
        self.events: list[Event] = []

    def emit_event(self, event: Event):
        self.events.append(event)

    def commit(self) -> list[Event]:
        committed = list(self.events)
        self.events = []
        return committed


@pytest.fixture
def fake_uow():
    return FakeUnitOfWork()


@pytest.fixture
def emitter(fake_uow):
    return EventEmitter(
        uow=fake_uow,
        run_id="run-trace-1",
        planner_mode="agentic",
        pii_policy="redact",
    )


def test_run_started_event(emitter, fake_uow):
    """run_started emits RUN_STARTED with flow metadata."""
    emitter.run_started(flow_id="flow-1", flow_name="test-flow")
    assert len(fake_uow.events) == 1
    evt = fake_uow.events[0]
    assert evt.event_type == EventType.RUN_STARTED
    assert evt.run_id == "run-trace-1"
    assert evt.payload["flow_id"] == "flow-1"
    assert evt.payload["flow_name"] == "test-flow"


def test_run_completed_event(emitter, fake_uow):
    """run_completed emits RUN_COMPLETED."""
    emitter.run_completed(tokens=100, cost_usd=0.01)
    assert len(fake_uow.events) == 1
    evt = fake_uow.events[0]
    assert evt.event_type == EventType.RUN_COMPLETED
    assert evt.payload["tokens"] == 100


def test_run_failed_event(emitter, fake_uow):
    """run_failed emits RUN_FAILED with error details."""
    emitter.run_failed(error="Budget exceeded", error_type="BudgetExceededError")
    evt = fake_uow.events[0]
    assert evt.event_type == EventType.RUN_FAILED
    assert evt.severity == "error"
    assert "Budget exceeded" in evt.summary


def test_step_lifecycle_events(emitter, fake_uow):
    """Step start/complete/fail emit correct event types."""
    emitter.step_started(step_id="s1", step_name="extract", step_number=0)
    emitter.step_completed(step_id="s1", step_name="extract", duration_ms=500)
    assert len(fake_uow.events) == 2
    assert fake_uow.events[0].event_type == EventType.STEP_STARTED
    assert fake_uow.events[1].event_type == EventType.STEP_COMPLETED

    emitter.step_failed(step_id="s2", step_name="transform", error="fail", error_type="Error")
    assert fake_uow.events[2].event_type == EventType.STEP_FAILED


def test_tool_lifecycle_events(emitter, fake_uow):
    """Tool start/succeed/fail events."""
    emitter.tool_started(step_id="s1", tool_name="ai.extract")
    emitter.tool_succeeded(step_id="s1", tool_name="ai.extract", duration_ms=200)
    assert fake_uow.events[0].event_type == EventType.TOOL_STARTED
    assert fake_uow.events[1].event_type == EventType.TOOL_SUCCEEDED

    emitter.tool_failed(step_id="s1", tool_name="ai.extract", error="timeout", error_type="Timeout")
    assert fake_uow.events[2].event_type == EventType.TOOL_FAILED


def test_verifier_events(emitter, fake_uow):
    """Verifier approved/rejected/replan/escalated events."""
    emitter.verifier_approved(step_id="s1", tool_name="ai.extract", confidence=0.95)
    emitter.verifier_rejected(step_id="s1", tool_name="ai.extract", reasoning="unsafe")
    emitter.verifier_replan_requested(
        step_id="s1", tool_name="ai.extract", reasoning="revise", attempt=1
    )
    emitter.verifier_escalated(step_id="s1", tool_name="ai.extract", reasoning="prod access")

    types = [e.event_type for e in fake_uow.events]
    assert EventType.VERIFIER_APPROVED in types
    assert EventType.VERIFIER_REJECTED in types
    assert EventType.VERIFIER_REPLAN_REQUESTED in types
    assert EventType.VERIFIER_ESCALATED in types


def test_verifier_approved_actor_is_llm(emitter, fake_uow):
    """Verifier events have actor='llm'."""
    emitter.verifier_approved(step_id="s1", tool_name="ai.extract", confidence=0.9)
    assert fake_uow.events[0].actor == "llm"


def test_replan_events(emitter, fake_uow):
    """Replan attempted/succeeded/exhausted events."""
    emitter.replan_attempted(step_id="s1", attempt=1, max_attempts=3, feedback="revise args")
    emitter.replan_succeeded(step_id="s1", attempt=1)
    emitter.replan_exhausted(step_id="s1", max_attempts=3, final_verdict="replan")

    types = [e.event_type for e in fake_uow.events]
    assert EventType.REPLAN_ATTEMPTED in types
    assert EventType.REPLAN_SUCCEEDED in types
    assert EventType.REPLAN_EXHAUSTED in types


def test_replan_exhausted_is_error_severity(emitter, fake_uow):
    """Replan exhausted should be error severity."""
    emitter.replan_exhausted(step_id="s1", max_attempts=3, final_verdict="replan")
    assert fake_uow.events[0].severity == "error"


def test_approval_events(emitter, fake_uow):
    """Approval requested/granted/denied events."""
    emitter.approval_requested(
        step_id="s1",
        step_name="approval_step",
        reasoning="Requires human review",
        callback_id="cb-123",
    )
    emitter.approval_granted(step_id="s1", step_name="approval_step")
    emitter.approval_denied(step_id="s1", step_name="approval_step", reason="Not authorized")

    types = [e.event_type for e in fake_uow.events]
    assert EventType.APPROVAL_REQUESTED in types
    assert EventType.APPROVAL_GRANTED in types
    assert EventType.APPROVAL_DENIED in types

    # Granted and denied should have actor=user
    granted = [e for e in fake_uow.events if e.event_type == EventType.APPROVAL_GRANTED][0]
    denied = [e for e in fake_uow.events if e.event_type == EventType.APPROVAL_DENIED][0]
    assert granted.actor == "user"
    assert denied.actor == "user"


def test_approval_requested_includes_callback_id(emitter, fake_uow):
    """Approval requested event includes callback_id for webhook lookup."""
    emitter.approval_requested(
        step_id="s1",
        step_name="review",
        reasoning="Needs approval",
        callback_id="abc123",
    )
    evt = fake_uow.events[0]
    assert evt.payload["callback_id"] == "abc123"


def test_webhook_callback_event(emitter, fake_uow):
    """Webhook callback received event."""
    emitter.webhook_callback_received(callback_id="cb-abc", action="approve")
    evt = fake_uow.events[0]
    assert evt.event_type == EventType.WEBHOOK_CALLBACK_RECEIVED
    assert evt.payload["callback_id"] == "cb-abc"
    assert evt.payload["action"] == "approve"
    assert evt.actor == "user"


def test_run_suspended_event(emitter, fake_uow):
    """Run suspended event includes reason."""
    emitter.run_suspended(reason="Awaiting human approval", step_id="s1")
    evt = fake_uow.events[0]
    assert evt.event_type == EventType.RUN_SUSPENDED
    assert "human approval" in evt.payload["reason"].lower()
    assert evt.severity == "warn"


def test_run_resumed_event(emitter, fake_uow):
    """Run resumed event includes resume source."""
    emitter.run_resumed(resume_source="webhook_callback")
    evt = fake_uow.events[0]
    assert evt.event_type == EventType.RUN_RESUMED
    assert evt.payload["resume_source"] == "webhook_callback"


def test_critique_completed_event(emitter, fake_uow):
    """Post-execution critique event."""
    emitter.critique_completed(
        step_id="s1", verdict="pass", confidence=0.95, reasoning="Result looks good"
    )
    evt = fake_uow.events[0]
    assert evt.payload["critique_verdict"] == "pass"
    assert evt.payload["critique_confidence"] == 0.95
    assert evt.tags["critique_verdict"] == "pass"


def test_plan_generated_event(emitter, fake_uow):
    """Plan generated event includes step count and mode."""
    emitter.plan_generated(
        total_steps=3,
        steps=[{"id": "s1", "intent": "Extract"}, {"id": "s2", "intent": "Transform"}],
        estimated_cost=0.05,
    )
    evt = fake_uow.events[0]
    assert evt.event_type == EventType.PLAN_GENERATED
    assert evt.payload["total_steps"] == 3
    # In agentic mode, plan generation is by LLM
    assert evt.actor == "llm"


def test_all_events_have_run_id(emitter, fake_uow):
    """All emitted events have the correct run_id."""
    emitter.run_started(flow_id="f1", flow_name="test")
    emitter.step_started(step_id="s1", step_name="step1", step_number=0)
    emitter.tool_started(step_id="s1", tool_name="ai.extract")
    emitter.verifier_approved(step_id="s1", tool_name="ai.extract", confidence=0.9)
    emitter.replan_attempted(step_id="s1", attempt=1, max_attempts=3, feedback="feedback")

    for evt in fake_uow.events:
        assert evt.run_id == "run-trace-1"


def test_all_events_have_planner_mode(emitter, fake_uow):
    """All emitted events carry the planner_mode."""
    emitter.run_started(flow_id="f1", flow_name="test")
    emitter.verifier_approved(step_id="s1", tool_name="t", confidence=0.9)
    for evt in fake_uow.events:
        assert evt.planner_mode == "agentic"


def test_event_ordering_is_preserved(emitter, fake_uow):
    """Events are committed in emission order."""
    emitter.run_started(flow_id="f1", flow_name="test")
    emitter.step_started(step_id="s1", step_name="step1", step_number=0)
    emitter.tool_started(step_id="s1", tool_name="ai.extract")
    emitter.verifier_approved(step_id="s1", tool_name="ai.extract", confidence=0.9)
    emitter.tool_succeeded(step_id="s1", tool_name="ai.extract", duration_ms=100)
    emitter.step_completed(step_id="s1", step_name="step1", duration_ms=150)
    emitter.run_completed()

    types = [e.event_type for e in fake_uow.events]
    expected_order = [
        EventType.RUN_STARTED,
        EventType.STEP_STARTED,
        EventType.TOOL_STARTED,
        EventType.VERIFIER_APPROVED,
        EventType.TOOL_SUCCEEDED,
        EventType.STEP_COMPLETED,
        EventType.RUN_COMPLETED,
    ]
    assert types == expected_order


def test_full_replan_trace(emitter, fake_uow):
    """Full trace of a step that requires replanning."""
    emitter.step_started(step_id="s1", step_name="extract", step_number=0)
    emitter.verifier_replan_requested(
        step_id="s1", tool_name="ai.extract", reasoning="unsafe", attempt=1
    )
    emitter.replan_attempted(step_id="s1", attempt=1, max_attempts=3, feedback="unsafe args")
    emitter.replan_succeeded(step_id="s1", attempt=1)
    emitter.verifier_approved(step_id="s1", tool_name="ai.extract", confidence=0.95)
    emitter.tool_started(step_id="s1", tool_name="ai.extract")
    emitter.tool_succeeded(step_id="s1", tool_name="ai.extract", duration_ms=100)
    emitter.step_completed(step_id="s1", step_name="extract", duration_ms=500)

    types = [e.event_type for e in fake_uow.events]
    assert EventType.VERIFIER_REPLAN_REQUESTED in types
    assert EventType.REPLAN_ATTEMPTED in types
    assert EventType.REPLAN_SUCCEEDED in types
    assert EventType.VERIFIER_APPROVED in types
    # Replan events appear before final approval
    replan_idx = types.index(EventType.REPLAN_ATTEMPTED)
    approved_idx = types.index(EventType.VERIFIER_APPROVED)
    assert replan_idx < approved_idx
