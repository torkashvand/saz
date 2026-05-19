"""Boundary tests for runs route ``sanitize_error``.

This function is a leak gate for production: any traceback or debug
payload that slips through reaches an operator UI. The existing
tests/unit/test_sanitize_error.py covers happy paths; this file
covers boundaries and mutation-resilient assertions.
"""

from saz.api.routes.runs import sanitize_error


def test_none_input_returns_none():
    assert sanitize_error(None, include_sensitive=False) is None
    assert sanitize_error(None, include_sensitive=True) is None


def test_empty_dict_returns_none():
    """Empty error must not become a stray empty dict — the route
    serializes it as null."""
    assert sanitize_error({}, include_sensitive=False) is None


def test_traceback_field_is_stripped_by_default():
    error = {"type": "X", "message": "boom", "traceback": "T"}
    out = sanitize_error(error, include_sensitive=False)
    assert out is not None
    assert "traceback" not in out
    assert out["type"] == "X"
    assert out["message"] == "boom"


def test_stack_trace_field_is_stripped_by_default():
    error = {"type": "X", "message": "boom", "stack_trace": "S"}
    out = sanitize_error(error, include_sensitive=False)
    assert out is not None
    assert "stack_trace" not in out


def test_include_sensitive_returns_full_dict_unchanged():
    error = {
        "type": "X",
        "message": "boom",
        "traceback": "T",
        "stack_trace": "S",
        "private_debug_field": {"secret": True},
    }
    out = sanitize_error(error, include_sensitive=True)
    assert out is error, "include_sensitive=True must pass the original dict through"


def test_unknown_top_level_field_is_stripped_by_default():
    error = {"type": "X", "message": "y", "totally_random_debug_key": 123}
    out = sanitize_error(error, include_sensitive=False)
    assert "totally_random_debug_key" not in out
    # The known operator-facing fields stayed
    assert out["type"] == "X" and out["message"] == "y"


def test_callback_id_is_preserved_for_webhook_panel():
    """The frontend needs callback_id to render the approval panel."""
    error = {"type": "HumanApprovalRequired", "callback_id": "cb_xyz"}
    out = sanitize_error(error, include_sensitive=False)
    assert out["callback_id"] == "cb_xyz"


def test_timeout_at_is_preserved_for_suspension_countdown():
    error = {"type": "HumanApprovalRequired", "timeout_at": "2026-05-19T10:00:00Z"}
    out = sanitize_error(error, include_sensitive=False)
    assert out["timeout_at"] == "2026-05-19T10:00:00Z"


def test_suspension_sweeper_fields_pass_through():
    """SuspensionSweeper writes original_type + timed_out_at on timeout."""
    error = {
        "type": "SuspensionTimeout",
        "original_type": "HumanApprovalRequired",
        "timed_out_at": "2026-05-19T11:00:00Z",
        "callback_id": "cb_abc",
    }
    out = sanitize_error(error, include_sensitive=False)
    assert out["original_type"] == "HumanApprovalRequired"
    assert out["timed_out_at"] == "2026-05-19T11:00:00Z"
    assert out["callback_id"] == "cb_abc"


def test_resolved_marker_passes_through():
    """Webhook callback marks errors as resolved; the UI reads this."""
    error = {"type": "X", "callback_id": "cb", "resolved": True}
    out = sanitize_error(error, include_sensitive=False)
    assert out["resolved"] is True


def test_status_code_passes_through():
    error = {"type": "HTTPError", "status_code": 500}
    out = sanitize_error(error, include_sensitive=False)
    assert out["status_code"] == 500


def test_no_safe_fields_present_returns_none():
    """If a payload has only debug fields, the sanitized result is None."""
    error = {"only_debug": "nothing operator-safe here"}
    out = sanitize_error(error, include_sensitive=False)
    assert out is None or out == {}, (
        "an error with no operator-safe fields must not leak the debug ones "
        f"as a non-empty dict; got {out!r}"
    )
