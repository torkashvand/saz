"""Tests for the outbound error sanitizer.

The sanitizer is the only thing standing between raw `Run.error` /
`Step.error` payloads (which may include stack traces) and the API
response. It must:

  * Strip stack traces / tracebacks unless include_sensitive=True.
  * Preserve the operator-facing fields the UI relies on, especially
    `callback_id` (drives the WebhookCallbackPanel + HumanApprovalPanel
    "Advanced" curl recipe) and `timeout_at` (drives the timeout audit).

Regressions here cause silent UX failures — the run-detail page
silently shows `undefined` in the callback URL.
"""

from saz.api.routes.runs import sanitize_error


def test_none_returns_none():
    assert sanitize_error(None, include_sensitive=False) is None


def test_empty_returns_none():
    assert sanitize_error({}, include_sensitive=False) is None


def test_strips_traceback_by_default():
    raw = {
        "type": "ToolFailed",
        "message": "API call failed",
        "traceback": "Traceback (most recent call last):\n  ...",
        "stack_trace": "at line 42",
    }
    out = sanitize_error(raw, include_sensitive=False)
    assert out == {"type": "ToolFailed", "message": "API call failed"}


def test_include_sensitive_returns_full_payload():
    raw = {
        "type": "ToolFailed",
        "message": "API call failed",
        "traceback": "secret stack",
    }
    assert sanitize_error(raw, include_sensitive=True) == raw


def test_preserves_callback_id_for_webhook_wait():
    """The WebhookCallbackPanel builds its URL from `callback_id`. If
    the sanitizer drops it, the UI shows `/undefined`."""
    raw = {
        "type": "WebhookWait",
        "message": "Webhook wait for step wait_for_completion_callback",
        "step_id": "wait_for_completion_callback",
        "callback_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
    }
    out = sanitize_error(raw, include_sensitive=False)
    assert out["callback_id"] == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
    assert out["step_id"] == "wait_for_completion_callback"
    assert out["type"] == "WebhookWait"


def test_preserves_callback_id_and_reasoning_for_approval():
    """HumanApprovalPanel surfaces `reasoning` in the gate context and
    `callback_id` in the Advanced section."""
    raw = {
        "type": "HumanApprovalRequired",
        "message": "Human approval required for step request_approval",
        "step_id": "request_approval",
        "reasoning": "Apply step would mutate production",
        "callback_id": "cb_abc123",
    }
    out = sanitize_error(raw, include_sensitive=False)
    assert out["callback_id"] == "cb_abc123"
    assert out["reasoning"] == "Apply step would mutate production"
    assert out["step_id"] == "request_approval"


def test_preserves_timeout_metadata():
    """The SuspensionSweeper reads `timeout_at` from the audit trail.
    The frontend doesn't display it yet, but the contract should
    expose it so downstream tooling can render a countdown."""
    raw = {
        "type": "WebhookWait",
        "message": "wait",
        "callback_id": "cb",
        "suspended_at": "2026-05-18T18:00:00+00:00",
        "timeout_at": "2026-05-19T18:00:00+00:00",
        "timeout_minutes": 1440.0,
    }
    out = sanitize_error(raw, include_sensitive=False)
    assert out["suspended_at"] == "2026-05-18T18:00:00+00:00"
    assert out["timeout_at"] == "2026-05-19T18:00:00+00:00"
    assert out["timeout_minutes"] == 1440.0


def test_preserves_suspension_timeout_audit_fields():
    """When the SuspensionSweeper times out a run it writes
    `original_type` (so the UI can show "was a WebhookWait") and
    `timed_out_at`. Both must reach the API consumer."""
    raw = {
        "type": "SuspensionTimeout",
        "message": "Suspension timed out for step wait. No callback received.",
        "step_id": "wait",
        "original_type": "WebhookWait",
        "timeout_at": "2026-05-18T17:00:00+00:00",
        "timed_out_at": "2026-05-18T17:01:00+00:00",
        "callback_id": "cb_late",
    }
    out = sanitize_error(raw, include_sensitive=False)
    assert out["original_type"] == "WebhookWait"
    assert out["timed_out_at"] == "2026-05-18T17:01:00+00:00"
    assert out["callback_id"] == "cb_late"


def test_preserves_resolved_marker_after_webhook_callback():
    """After a webhook callback resumes a run, the webhook handler
    preserves `callback_id` and adds `resolved: True`. The sanitizer
    must keep both so duplicate callbacks return already_processed
    with the right context."""
    raw = {
        "type": "HumanApprovalRequired",
        "message": "Human approval required",
        "step_id": "approve",
        "callback_id": "cb_resolved",
        "resolved": True,
    }
    out = sanitize_error(raw, include_sensitive=False)
    assert out["callback_id"] == "cb_resolved"
    assert out["resolved"] is True


def test_drops_unknown_debug_fields():
    """Anything not on the whitelist is dropped — including arbitrary
    debug payloads that might leak internal state."""
    raw = {
        "type": "ToolFailed",
        "message": "boom",
        "internal_state": {"db_password": "leak"},
        "raw_response": "<entire HTML page>",
        "stack_trace": "...",
    }
    out = sanitize_error(raw, include_sensitive=False)
    assert "internal_state" not in out
    assert "raw_response" not in out
    assert "stack_trace" not in out


def test_preserves_status_code():
    raw = {"type": "HttpError", "message": "Bad request", "status_code": 400}
    out = sanitize_error(raw, include_sensitive=False)
    assert out["status_code"] == 400
