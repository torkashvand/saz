"""Unit tests for _attach_timeout_metadata.

This helper is the contract between the executor (which suspends a run)
and the SuspensionSweeper (which reaps timed-out suspensions). The fields
it writes — ``suspended_at``, ``timeout_at``, ``timeout_minutes`` — are
read by SQL queries and by the frontend, so we pin the shape here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from saz.engine.executor import (
    _DEFAULT_SUSPENSION_TIMEOUT_MINUTES,
    _MIN_SUSPENSION_TIMEOUT_MINUTES,
    _attach_timeout_metadata,
)


def _delta_minutes(suspended_at_iso: str, timeout_at_iso: str) -> float:
    suspended = datetime.fromisoformat(suspended_at_iso)
    timeout = datetime.fromisoformat(timeout_at_iso)
    return (timeout - suspended).total_seconds() / 60.0


def test_uses_timeout_minutes_when_declared():
    payload: dict = {"type": "WebhookWait"}
    _attach_timeout_metadata(payload, {"timeout_minutes": 30})
    assert _delta_minutes(payload["suspended_at"], payload["timeout_at"]) == 30.0
    assert payload["timeout_minutes"] == 30.0


def test_uses_timeout_seconds_when_declared():
    payload: dict = {"type": "WebhookWait"}
    _attach_timeout_metadata(payload, {"timeout_seconds": 600})
    assert _delta_minutes(payload["suspended_at"], payload["timeout_at"]) == 10.0
    assert payload["timeout_minutes"] == 10.0


def test_timeout_minutes_takes_precedence_over_seconds():
    payload: dict = {"type": "WebhookWait"}
    _attach_timeout_metadata(payload, {"timeout_minutes": 5, "timeout_seconds": 9999})
    assert payload["timeout_minutes"] == 5.0


def test_falls_back_to_default_when_no_timeout_declared():
    """Suspensions without an explicit timeout still get a deadline so
    they cannot pile up forever. The default is intentionally generous
    (24h)."""
    payload: dict = {"type": "HumanApprovalRequired"}
    _attach_timeout_metadata(payload, {})
    assert payload["timeout_minutes"] == float(_DEFAULT_SUSPENSION_TIMEOUT_MINUTES)


def test_falls_back_to_default_when_timeout_is_zero_or_negative():
    """A zero or negative timeout is treated as 'not declared', not as
    'fail immediately'. This guards against authoring mistakes that
    would otherwise trip every suspension on the first sweep."""
    for bad_value in (0, -10, -1.5):
        payload: dict = {}
        _attach_timeout_metadata(payload, {"timeout_minutes": bad_value})
        assert payload["timeout_minutes"] == float(_DEFAULT_SUSPENSION_TIMEOUT_MINUTES)


def test_clamps_positive_timeout_below_minimum_floor():
    """A YAML author writing ``timeout_minutes: 0.001`` should not get a
    near-instant timeout — the SuspensionSweeper would reap the run before
    any approver / external system could act. Positive sub-minimum values
    are clamped up to ``_MIN_SUSPENSION_TIMEOUT_MINUTES`` (the sweeper's
    own polling resolution)."""
    for tiny in (0.001, 0.1, 0.5):
        payload: dict = {}
        _attach_timeout_metadata(payload, {"timeout_minutes": tiny})
        assert payload["timeout_minutes"] == _MIN_SUSPENSION_TIMEOUT_MINUTES, (
            f"timeout_minutes={tiny} should clamp to "
            f"{_MIN_SUSPENSION_TIMEOUT_MINUTES}, got {payload['timeout_minutes']}"
        )
        # Also confirm the deadline reflects the clamped minutes.
        assert (
            _delta_minutes(payload["suspended_at"], payload["timeout_at"])
            == _MIN_SUSPENSION_TIMEOUT_MINUTES
        )


def test_does_not_clamp_values_at_or_above_minimum_floor():
    """Values at or above the floor must pass through unchanged so the
    clamp doesn't silently rewrite a legitimately-declared short timeout."""
    payload: dict = {}
    _attach_timeout_metadata(payload, {"timeout_minutes": _MIN_SUSPENSION_TIMEOUT_MINUTES})
    assert payload["timeout_minutes"] == _MIN_SUSPENSION_TIMEOUT_MINUTES

    payload2: dict = {}
    _attach_timeout_metadata(payload2, {"timeout_minutes": 2.5})
    assert payload2["timeout_minutes"] == 2.5


def test_ignores_non_numeric_timeout_values():
    payload: dict = {}
    _attach_timeout_metadata(payload, {"timeout_minutes": "not-a-number"})
    assert payload["timeout_minutes"] == float(_DEFAULT_SUSPENSION_TIMEOUT_MINUTES)


def test_handles_none_input_template():
    """A step with no params at all (input_template=None) still gets
    bounded by the default timeout."""
    payload: dict = {}
    _attach_timeout_metadata(payload, None)
    assert "timeout_at" in payload
    assert "suspended_at" in payload


def test_suspended_at_is_close_to_now():
    payload: dict = {}
    before = datetime.now(UTC)
    _attach_timeout_metadata(payload, {"timeout_minutes": 1})
    after = datetime.now(UTC)
    suspended = datetime.fromisoformat(payload["suspended_at"])
    assert before - timedelta(seconds=2) <= suspended <= after + timedelta(seconds=2)


def test_preserves_existing_payload_fields():
    """The helper augments a payload; it must not overwrite caller fields."""
    payload: dict = {
        "type": "WebhookWait",
        "step_id": "wait_step",
        "callback_id": "abc123",
        "message": "Webhook wait for step wait_step",
    }
    _attach_timeout_metadata(payload, {"timeout_minutes": 5})
    assert payload["type"] == "WebhookWait"
    assert payload["step_id"] == "wait_step"
    assert payload["callback_id"] == "abc123"
    assert payload["message"].startswith("Webhook wait")
