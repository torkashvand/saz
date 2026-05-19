"""Boundary tests for PolicyEngine.check_tool_call decisions.

Coverage focus:
  - rate-limit boundary (exactly at the limit, one over).
  - budget exhaustion turns into a block, not a pass.
  - model vs outbound vs other tool classification dispatches correctly.

Mutation testing on PolicyEngine is high-value because the function is a
safety gate that returns (allowed, reason). A flipped boolean returns the
opposite verdict and the executor silently runs an unsafe call.
"""

import pytest

from saz.policies.policy_engine import MODEL_TOOLS, OUTBOUND_TOOLS, PolicyEngine
from saz.policies.rate_limiter import RateLimiter


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine(
        rate_limiter=RateLimiter(calls_per_minute=3, calls_per_hour=100),
        enforce_pii_redaction=True,
    )


def test_calls_within_per_minute_limit_allowed(engine):
    for _ in range(3):
        allowed, reason = engine.check_tool_call("http_request", {"method": "GET"}, "r1")
        assert allowed is True, reason


def test_call_one_over_per_minute_limit_blocked(engine):
    for _ in range(3):
        engine.check_tool_call("http_request", {"method": "GET"}, "r1")
    allowed, reason = engine.check_tool_call("http_request", {"method": "GET"}, "r1")
    assert allowed is False
    assert "Rate limit" in reason


def test_model_tool_classification_complete():
    """Every ai.* op in AI_OPS must be classified as a MODEL_TOOL."""
    from saz.agents.ai_ops import AI_OPS

    missing = set(AI_OPS.keys()) - MODEL_TOOLS
    assert not missing, (
        "AI ops not classified as MODEL_TOOLS — model-input tokenization "
        f"will skip them: {sorted(missing)}"
    )


def test_outbound_tool_classification_includes_known_outbound():
    expected_outbound = {"http_request", "webhook_emit", "ansible_run"}
    missing = expected_outbound - OUTBOUND_TOOLS
    assert not missing, (
        f"OUTBOUND_TOOLS must include {sorted(expected_outbound)}; missing "
        f"{sorted(missing)}. Outbound PII checks won't fire for missing tools."
    )


def test_model_tool_with_pii_in_args_not_blocked(engine):
    """Model tools tokenize PII before calling out — must not be blocked."""
    allowed, reason = engine.check_tool_call(
        "ai.extract",
        {"instruction": "do", "data": {"email": "user@example.com"}},
        "r2",
    )
    assert allowed is True, reason


def test_outbound_tool_with_pii_on_disallowed_path_blocked(engine):
    """Outbound tool with detected PII on a non-allow-listed path must be blocked."""
    allowed, reason = engine.check_tool_call(
        "http_request",
        {
            "method": "POST",
            "url": "https://e.com",
            "body": {"comment": "reach me at user@example.com"},
        },
        "r3",
    )
    assert allowed is False, (
        f"outbound tool with unmasked email in body must be blocked; got "
        f"allowed={allowed} reason={reason!r}"
    )
    assert "PII" in reason


def test_outbound_tool_with_pii_on_allowed_path_passes(engine):
    """An operator-declared allow-list for a path lets the tool through."""
    engine.pii_allow_lists = {"http_request": ["body.comment"]}
    allowed, _ = engine.check_tool_call(
        "http_request",
        {
            "method": "POST",
            "url": "https://e.com",
            "body": {"comment": "reach me at user@example.com"},
        },
        "r4",
    )
    assert allowed is True


def test_independent_runs_share_per_tool_per_minute_bucket(engine):
    """The per-tool rate-limit bucket is keyed by tool only; same-tool calls
    across run ids share it. This pins the current contract — if the policy
    ever needs to be per-(tool, run), update this test deliberately."""
    for _ in range(3):
        engine.check_tool_call("http_request", {"method": "GET"}, "run_a")
    allowed, reason = engine.check_tool_call("http_request", {"method": "GET"}, "run_b")
    assert allowed is False, (
        "shared per-tool bucket means run_b is blocked once run_a hit the cap; "
        f"got allowed={allowed} reason={reason!r}"
    )
