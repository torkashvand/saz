"""Behavioral tests for RateLimiter.

The rate limiter is the last gate before an external tool call. If it
silently allows over-budget calls (or silently rejects legitimate ones),
runs can exfiltrate spend or stall.
"""

from saz.policies.rate_limiter import RateLimiter


def test_rate_limiter_allows_until_exact_limit() -> None:
    """`calls_per_minute` defines the cap as a strict upper bound — calls 1..N
    are allowed, the (N+1)th is rejected."""
    limiter = RateLimiter(calls_per_minute=3, calls_per_hour=100)

    decisions = [limiter.check_and_record("http_request", "r1") for _ in range(3)]
    assert all(ok for ok, _ in decisions), decisions

    blocked_ok, reason = limiter.check_and_record("http_request", "r1")
    assert blocked_ok is False
    assert "exceeded" in reason and "3 calls/minute" in reason


def test_rate_limiter_blocks_after_limit_with_clear_reason() -> None:
    limiter = RateLimiter(calls_per_minute=1, calls_per_hour=100)
    ok1, _ = limiter.check_and_record("http_request", "r1")
    ok2, reason = limiter.check_and_record("http_request", "r1")
    assert ok1 is True
    assert ok2 is False
    assert "http_request" in reason
    assert "1 calls/minute" in reason


def test_rate_limiter_tracks_per_tool_independently() -> None:
    """Each tool gets its own bucket — a saturated tool must not affect siblings."""
    limiter = RateLimiter(calls_per_minute=1, calls_per_hour=100)
    limiter.per_tool_rpm["http_request"] = 1

    ok1, _ = limiter.check_and_record("http_request", "r1")
    ok2, _ = limiter.check_and_record("http_request", "r1")
    other_ok, _ = limiter.check_and_record("webhook_emit", "r1")

    assert ok1 is True
    assert ok2 is False, "http_request capped at 1"
    assert other_ok is True, "webhook_emit should not inherit http_request bucket"


def test_rate_limiter_per_run_hour_limit_blocks_across_tools() -> None:
    """`calls_per_hour` is keyed by run_id and should block once any combination
    of tools exhausts the hourly cap."""
    limiter = RateLimiter(calls_per_minute=100, calls_per_hour=2)

    a_ok, _ = limiter.check_and_record("http_request", "r1")
    b_ok, _ = limiter.check_and_record("webhook_emit", "r1")
    c_ok, reason = limiter.check_and_record("artifact.store", "r1")

    assert a_ok is True
    assert b_ok is True
    assert c_ok is False
    assert "2 calls/hour" in reason


def test_rate_limiter_per_run_hour_limit_is_isolated_per_run() -> None:
    limiter = RateLimiter(calls_per_minute=100, calls_per_hour=1)
    a_ok, _ = limiter.check_and_record("http_request", "run-A")
    b_ok, _ = limiter.check_and_record("http_request", "run-B")
    assert a_ok is True
    assert b_ok is True, "Run B has its own hourly bucket"


def test_rate_limiter_get_stats_reports_current_usage_and_remaining() -> None:
    limiter = RateLimiter(calls_per_minute=100, calls_per_hour=5)
    for _ in range(3):
        limiter.check_and_record("http_request", "r1")

    stats = limiter.get_stats("r1")
    assert stats["calls_last_hour"] == 3
    assert stats["limit_per_hour"] == 5
    assert stats["remaining_calls"] == 2


def test_rate_limiter_get_stats_for_unknown_run_returns_zero_usage() -> None:
    limiter = RateLimiter(calls_per_minute=10, calls_per_hour=100)
    stats = limiter.get_stats("never-seen")
    assert stats["calls_last_hour"] == 0
    assert stats["limit_per_hour"] == 100
    assert stats["remaining_calls"] == 100


def test_rate_limiter_reset_clears_hour_bucket() -> None:
    limiter = RateLimiter(calls_per_minute=100, calls_per_hour=1)
    ok1, _ = limiter.check_and_record("http_request", "r1")
    ok2, _ = limiter.check_and_record("http_request", "r1")
    assert ok1 is True
    assert ok2 is False

    limiter.reset("r1")

    ok3, _ = limiter.check_and_record("http_request", "r1")
    assert ok3 is True, "After reset, hour bucket must be empty"


def test_rate_limiter_reset_unknown_run_is_safe() -> None:
    limiter = RateLimiter()
    limiter.reset("never-seen")


def test_rate_limiter_per_tool_rpm_override_takes_precedence() -> None:
    """A per-tool rpm override must REPLACE the global default for that tool."""
    limiter = RateLimiter(calls_per_minute=10, calls_per_hour=100)
    limiter.per_tool_rpm["http_request"] = 2

    allowed = [limiter.check_and_record("http_request", "r1")[0] for _ in range(3)]
    assert allowed == [True, True, False]
