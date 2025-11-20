"""Tests for event schema and Event dataclass."""

from datetime import datetime

from saz.domain.event_schema import Event, EventType


def test_event_type_enum():
    """EventType enum has expected values."""
    assert EventType.RUN_STARTED.value == "run.started"
    assert EventType.STEP_COMPLETED.value == "step.completed"
    assert EventType.TOOL_FAILED.value == "tool.failed"
    assert EventType.POLICY_PII_REDACTED.value == "policy.pii.redacted"


def test_event_defaults():
    """Event dataclass has correct defaults."""
    event = Event(run_id="test_run", event_type=EventType.RUN_STARTED)

    assert event.run_id == "test_run"
    assert event.event_type == EventType.RUN_STARTED
    assert event.id.startswith("evt_")
    assert len(event.id) == 16  # evt_ + 12 hex chars
    assert isinstance(event.timestamp, datetime)
    assert event.schema_version == 1
    assert event.severity == "info"
    assert event.actor == "system"
    assert event.planner_mode == "deterministic"
    assert event.step_id is None
    assert event.correlation_id is None
    assert event.summary == ""
    assert event.payload == {}
    assert event.tags == {}


def test_event_custom_fields():
    """Event accepts custom field values."""
    now = datetime(2025, 1, 1, 12, 0, 0)
    event = Event(
        id="custom_id",
        event_type=EventType.TOOL_FAILED,
        timestamp=now,
        run_id="run_123",
        step_id="step_456",
        correlation_id="corr_789",
        planner_mode="agentic",
        severity="error",
        actor="llm",
        summary="Tool execution failed",
        payload={"tool": "http_request", "error": "timeout"},
        tags={"flow": "test_flow"},
    )

    assert event.id == "custom_id"
    assert event.event_type == EventType.TOOL_FAILED
    assert event.timestamp == now
    assert event.run_id == "run_123"
    assert event.step_id == "step_456"
    assert event.correlation_id == "corr_789"
    assert event.planner_mode == "agentic"
    assert event.severity == "error"
    assert event.actor == "llm"
    assert event.summary == "Tool execution failed"
    assert event.payload == {"tool": "http_request", "error": "timeout"}
    assert event.tags == {"flow": "test_flow"}


def test_event_to_dict():
    """Event.to_dict() serializes correctly."""
    now = datetime(2025, 1, 1, 12, 0, 0)
    event = Event(
        event_type=EventType.RUN_STARTED,
        run_id="run_123",
        timestamp=now,
        summary="Run started",
        payload={"flow_id": "flow_1"},
    )

    result = event.to_dict()

    assert result["event_type"] == "run.started"
    assert result["run_id"] == "run_123"
    assert result["timestamp"] == "2025-01-01T12:00:00"
    assert result["summary"] == "Run started"
    assert result["payload"] == {"flow_id": "flow_1"}
    assert result["severity"] == "info"
    assert result["schema_version"] == 1


def test_event_from_dict():
    """Event.from_dict() deserializes correctly."""
    data = {
        "id": "evt_test123",
        "event_type": "tool.succeeded",
        "timestamp": "2025-01-01T12:00:00",
        "run_id": "run_123",
        "step_id": "step_456",
        "severity": "info",
        "actor": "system",
        "planner_mode": "deterministic",
        "summary": "Tool completed",
        "payload": {"duration_ms": 1500},
        "tags": {"tool": "http_request"},
        "schema_version": 1,
        "correlation_id": None,
    }

    event = Event.from_dict(data)

    assert event.id == "evt_test123"
    assert event.event_type == EventType.TOOL_SUCCEEDED
    assert event.timestamp == datetime(2025, 1, 1, 12, 0, 0)
    assert event.run_id == "run_123"
    assert event.step_id == "step_456"
    assert event.summary == "Tool completed"
    assert event.payload == {"duration_ms": 1500}
    assert event.tags == {"tool": "http_request"}


def test_event_round_trip():
    """Event survives to_dict/from_dict round-trip."""
    original = Event(
        event_type=EventType.STEP_COMPLETED,
        run_id="run_xyz",
        step_id="step_abc",
        severity="info",
        summary="Step done",
        payload={"result": "success"},
    )

    # Round trip
    data = original.to_dict()
    restored = Event.from_dict(data)

    assert restored.id == original.id
    assert restored.event_type == original.event_type
    assert restored.run_id == original.run_id
    assert restored.step_id == original.step_id
    assert restored.severity == original.severity
    assert restored.summary == original.summary
    assert restored.payload == original.payload
