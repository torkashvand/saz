"""Tests for telemetry system."""

import pytest

from saz.telemetry import (
    CritiqueEvent,
    PIIStats,
    PlanGeneratedEvent,
    PolicyCheckEvent,
    RunProgressEvent,
    StepGroundedEvent,
    TelemetryConfig,
    TelemetryLevel,
    TelemetrySanitizer,
    ToolEndEvent,
    ToolStartEvent,
    UsageEvent,
)

# ------------------------------- Config Tests ------------------------------------------


def test_telemetry_config_default():
    """Test default telemetry config."""
    config = TelemetryConfig()
    assert config.trace_level == TelemetryLevel.META
    assert config.sample_rate == 1.0
    assert config.is_enabled()


def test_telemetry_config_from_dsl():
    """Test telemetry config from DSL."""
    config = TelemetryConfig.from_dsl({"trace_level": "verbose", "sample_rate": 0.5})
    assert config.trace_level == TelemetryLevel.VERBOSE
    assert config.sample_rate == 0.5


def test_telemetry_config_from_dsl_invalid_level():
    """Test telemetry config with invalid level falls back to meta."""
    config = TelemetryConfig.from_dsl({"trace_level": "invalid"})
    assert config.trace_level == TelemetryLevel.META


def test_telemetry_config_from_dsl_none():
    """Test telemetry config from None DSL."""
    config = TelemetryConfig.from_dsl(None)
    assert config.trace_level == TelemetryLevel.META
    assert config.sample_rate == 1.0


def test_telemetry_level_off():
    """Test telemetry disabled when level is off."""
    config = TelemetryConfig(trace_level=TelemetryLevel.OFF)
    assert not config.is_enabled()
    assert not config.should_emit(TelemetryLevel.META)
    assert not config.should_emit(TelemetryLevel.BRIEF)
    assert not config.should_emit(TelemetryLevel.VERBOSE)


def test_telemetry_level_meta():
    """Test meta level only emits meta events."""
    config = TelemetryConfig(trace_level=TelemetryLevel.META)
    assert config.should_emit(TelemetryLevel.META)
    assert not config.should_emit(TelemetryLevel.BRIEF)
    assert not config.should_emit(TelemetryLevel.VERBOSE)


def test_telemetry_level_brief():
    """Test brief level emits meta and brief events."""
    config = TelemetryConfig(trace_level=TelemetryLevel.BRIEF)
    assert config.should_emit(TelemetryLevel.META)
    assert config.should_emit(TelemetryLevel.BRIEF)
    assert not config.should_emit(TelemetryLevel.VERBOSE)


def test_telemetry_level_verbose():
    """Test verbose level emits all events."""
    config = TelemetryConfig(trace_level=TelemetryLevel.VERBOSE)
    assert config.should_emit(TelemetryLevel.META)
    assert config.should_emit(TelemetryLevel.BRIEF)
    assert config.should_emit(TelemetryLevel.VERBOSE)


# ------------------------------- Sanitizer Tests ---------------------------------------


@pytest.fixture
def sanitizer():
    """Create telemetry sanitizer."""
    return TelemetrySanitizer()


def test_sanitizer_input_summary_basic(sanitizer):
    """Test basic input summarization."""
    summary = sanitizer.sanitize_input_summary({"name": "test", "count": 42, "active": True})
    assert "name=test" in summary
    assert "count=42" in summary
    assert "active=True" in summary


def test_sanitizer_input_summary_with_pii(sanitizer):
    """Test input summarization redacts PII."""
    summary = sanitizer.sanitize_input_summary({"email": "test@example.com"})
    assert "email" in summary
    assert "test@example.com" not in summary
    assert "<REDACTED>" in summary


def test_sanitizer_input_summary_nested(sanitizer):
    """Test input summarization with nested structures."""
    summary = sanitizer.sanitize_input_summary({"data": {"nested": "value"}, "items": [1, 2, 3]})
    assert "data:dict[1]" in summary
    assert "items:list[3]" in summary
    assert "nested" not in summary  # Nested keys not shown


def test_sanitizer_input_summary_truncation(sanitizer):
    """Test input summary is truncated to max length."""
    long_input = {f"key{i}": f"value{i}" for i in range(100)}
    summary = sanitizer.sanitize_input_summary(long_input)
    assert len(summary) <= sanitizer.MAX_SUMMARY_LENGTH


def test_sanitizer_output_summary_dict(sanitizer):
    """Test output summary for dict."""
    summary = sanitizer.sanitize_output_summary({"result": "success", "count": 42})
    assert "dict[2]" in summary
    assert "result" in summary
    assert "count" in summary


def test_sanitizer_output_summary_list(sanitizer):
    """Test output summary for list."""
    summary = sanitizer.sanitize_output_summary([1, 2, 3, 4, 5])
    assert summary == "list[5]"


def test_sanitizer_output_summary_string_with_pii(sanitizer):
    """Test output summary redacts PII from strings."""
    summary = sanitizer.sanitize_output_summary("Contact test@example.com")
    assert "test@example.com" not in summary
    assert "<REDACTED>" in summary


def test_sanitizer_output_summary_null(sanitizer):
    """Test output summary for None."""
    summary = sanitizer.sanitize_output_summary(None)
    assert summary == "null"


def test_sanitizer_intent_extraction(sanitizer):
    """Test intent extraction from step."""

    class MockStep:
        description = "Extract data from input"
        action = "tool.call"

    step = MockStep()
    intent = sanitizer.sanitize_intent(step)
    assert "Extract data" in intent


def test_sanitizer_intent_with_pii(sanitizer):
    """Test intent extraction redacts PII."""

    class MockStep:
        description = "Send email to test@example.com"

    step = MockStep()
    intent = sanitizer.sanitize_intent(step)
    assert "test@example.com" not in intent
    assert "<REDACTED>" in intent


def test_sanitizer_critique_summary(sanitizer):
    """Test critique summarization."""
    critique = {
        "verdict": "PASS",
        "confidence": 0.95,
        "issues": [],
    }
    summary = sanitizer.sanitize_critique_summary(critique)
    assert "PASS" in summary
    assert "95%" in summary


def test_sanitizer_critique_summary_with_issues(sanitizer):
    """Test critique summary includes first issue."""
    critique = {
        "verdict": "FAIL",
        "confidence": 0.5,
        "issues": ["First issue here", "Second issue"],
    }
    summary = sanitizer.sanitize_critique_summary(critique)
    assert "FAIL" in summary
    assert "50%" in summary
    assert "First issue" in summary


def test_sanitizer_schema_view(sanitizer):
    """Test schema view generation."""
    schema = sanitizer.get_schema_view(
        {"name": "test", "count": 42, "items": [1, 2], "data": {"nested": "val"}}
    )
    assert schema["name"] == "str"
    assert schema["count"] == "int"
    assert schema["items"] == "list[2]"
    assert schema["data"] == "dict[1]"


# ------------------------------- Event Tests -------------------------------------------


def test_plan_generated_event():
    """Test PlanGeneratedEvent serialization."""
    event = PlanGeneratedEvent(
        run_id="run-123",
        total_steps=3,
        steps=[
            {"id": "step1", "intent": "Do something", "deps": []},
            {"id": "step2", "intent": "Do another", "deps": ["step1"]},
        ],
    )
    data = event.to_dict()
    assert data["type"] == "trace.plan"
    assert data["run_id"] == "run-123"
    assert data["total_steps"] == 3
    assert len(data["steps"]) == 2


def test_step_grounded_event():
    """Test StepGroundedEvent serialization."""
    event = StepGroundedEvent(
        run_id="run-123",
        step_id="step1",
        intent="Extract data",
        input_summary="data:dict[3], count=42",
    )
    data = event.to_dict()
    assert data["type"] == "trace.step.grounded"
    assert data["step_id"] == "step1"
    assert data["intent"] == "Extract data"
    assert "input_summary" in data


def test_policy_check_event():
    """Test PolicyCheckEvent serialization."""
    pii_stats = PIIStats(tokenized_count=2, detokenized_paths=[], blocked_paths=["body.email"])
    event = PolicyCheckEvent(
        run_id="run-123",
        step_id="step1",
        tool="http_request",
        allowed=False,
        reason="PII detected",
        pii_stats=pii_stats,
    )
    data = event.to_dict()
    assert data["type"] == "trace.policy.check"
    assert data["allowed"] is False
    assert data["reason"] == "PII detected"
    assert data["pii_stats"]["tokenized_count"] == 2
    assert "blocked_paths" in data["pii_stats"]


def test_tool_start_event():
    """Test ToolStartEvent serialization."""
    event = ToolStartEvent(run_id="run-123", step_id="step1", tool="ai.extract", attempt=1)
    data = event.to_dict()
    assert data["type"] == "trace.tool.start"
    assert data["tool"] == "ai.extract"
    assert data["attempt"] == 1


def test_tool_end_event():
    """Test ToolEndEvent serialization."""
    event = ToolEndEvent(
        run_id="run-123",
        step_id="step1",
        tool="ai.extract",
        duration_ms=1234.56,
        status="success",
    )
    data = event.to_dict()
    assert data["type"] == "trace.tool.end"
    assert data["status"] == "success"
    assert data["duration_ms"] == 1234.56


def test_tool_end_event_with_error():
    """Test ToolEndEvent with error."""
    event = ToolEndEvent(
        run_id="run-123",
        step_id="step1",
        tool="http_request",
        duration_ms=100.0,
        status="error",
        error_type="ConnectionError",
    )
    data = event.to_dict()
    assert data["status"] == "error"
    assert data["error_type"] == "ConnectionError"


def test_critique_event():
    """Test CritiqueEvent serialization."""
    event = CritiqueEvent(
        run_id="run-123",
        step_id="step1",
        verdict="PASS",
        confidence=0.95,
        issues=[],
        summary="PASS (95%)",
    )
    data = event.to_dict()
    assert data["type"] == "trace.critique"
    assert data["verdict"] == "PASS"
    assert data["confidence"] == 0.95


def test_critique_event_limits_issues():
    """Test CritiqueEvent limits issues to 5."""
    event = CritiqueEvent(
        run_id="run-123",
        step_id="step1",
        verdict="FAIL",
        confidence=0.5,
        issues=[f"Issue {i}" for i in range(10)],
        summary="FAIL",
    )
    data = event.to_dict()
    assert len(data["issues"]) == 5


def test_usage_event():
    """Test UsageEvent serialization."""
    event = UsageEvent(
        run_id="run-123",
        step_id="step1",
        tokens=1000,
        cost_usd=0.05,
        duration_ms=2500.0,
    )
    data = event.to_dict()
    assert data["type"] == "trace.usage"
    assert data["tokens"] == 1000
    assert data["cost_usd"] == 0.05
    assert data["duration_ms"] == 2500.0


def test_run_progress_event():
    """Test RunProgressEvent serialization."""
    event = RunProgressEvent(run_id="run-123", completed=2, total=5, percent=40.0)
    data = event.to_dict()
    assert data["type"] == "trace.progress"
    assert data["completed"] == 2
    assert data["total"] == 5
    assert data["percent"] == 40.0
