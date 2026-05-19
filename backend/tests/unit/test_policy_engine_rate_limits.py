"""PolicyEngine.initialize_from_dsl must consume the compiler's rate_limits shape.

Bug being pinned: the compiler accepts and preserves DSL of shape:

    policies:
      rate_limits:
        http_request:
          rpm: 3

…and stores it as ``{"http_request": {"rpm": 3}}``. But PolicyEngine.
initialize_from_dsl() reads ``rate_limits.get("calls_per_minute", 10)`` and
``rate_limits.get("calls_per_hour", 100)``. The per-tool RPM values are
silently dropped, so authors think they configured a 3-rpm cap on
http_request while the runtime quietly uses the default global limits.
"""

from saz.policies.policy_engine import PolicyEngine
from saz.policies.rate_limiter import RateLimiter


def test_initialize_from_dsl_applies_per_tool_rpm():
    """A per-tool rpm from the compiled policies dict must reach the limiter.

    Today the DSL key is ignored entirely — the limiter is configured from
    `calls_per_minute` (which doesn't exist in the compiled shape) so it
    falls back to the global default of 10. This test fails until either:
      - PolicyEngine.initialize_from_dsl reads the per-tool rpm, or
      - the compiler is changed to emit calls_per_minute/calls_per_hour
        and the DSL field is renamed (parity).
    """
    engine = PolicyEngine(rate_limiter=RateLimiter(calls_per_minute=10, calls_per_hour=100))

    # Shape matches what compile_dsl emits for the DSL above.
    policies_dict = {
        "rate_limits": {"http_request": {"rpm": 3}},
    }
    engine.initialize_from_dsl(run_id="r1", policies_dict=policies_dict)

    # Probe the limiter: call http_request 4 times. With rpm=3 declared, the
    # 4th must be rejected. With the bug present the global default of 10
    # lets all 4 through.
    decisions = [engine.rate_limiter.check_and_record("http_request", "r1") for _ in range(4)]
    allowed = [ok for ok, _ in decisions]

    assert allowed[:3] == [True, True, True], "First three calls should be allowed under rpm=3"
    assert allowed[3] is False, (
        "Fourth http_request call must be blocked when DSL declares rpm=3 — "
        f"all four allowed today: {decisions}. The per-tool rpm from the DSL "
        "is never read by PolicyEngine.initialize_from_dsl."
    )


def test_initialize_from_dsl_other_tools_unaffected_by_one_tool_rpm():
    """Per-tool rpm on http_request must not silently limit other tools."""
    engine = PolicyEngine(rate_limiter=RateLimiter(calls_per_minute=10, calls_per_hour=100))
    engine.initialize_from_dsl(
        run_id="r1",
        policies_dict={"rate_limits": {"http_request": {"rpm": 1}}},
    )

    # http_request: only 1 allowed
    h_ok, _ = engine.rate_limiter.check_and_record("http_request", "r1")
    h_blocked, _ = engine.rate_limiter.check_and_record("http_request", "r1")
    assert h_ok is True
    assert h_blocked is False, "Sanity: http_request capped at rpm=1"

    # Some other tool not mentioned in DSL: should follow some sensible default,
    # NOT inherit http_request's rpm=1. Make several calls and assert at least
    # a handful go through (don't pin the exact number — that's a separate
    # design decision; just don't be silently throttled to 1).
    other_allowed = sum(
        1 for _ in range(5) if engine.rate_limiter.check_and_record("webhook_emit", "r1")[0]
    )
    assert other_allowed >= 3, (
        f"webhook_emit was throttled to {other_allowed} calls — looks like "
        f"http_request's rpm leaked into the global limit."
    )
