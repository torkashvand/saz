"""Rate Limiter - Prevents excessive tool calls."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

import structlog

logger = structlog.get_logger(__name__)


class RateLimiter:
    """
    Token bucket rate limiter for tool calls.

    Enforces:
    - Max calls per minute per tool
    - Max calls per hour per workflow
    """

    def __init__(self, calls_per_minute: int = 10, calls_per_hour: int = 100):
        self.calls_per_minute = calls_per_minute
        self.calls_per_hour = calls_per_hour
        # Per-tool RPM overrides set by PolicyEngine.initialize_from_dsl from
        # DSL `policies.rate_limits.<tool>.rpm`. Falls back to
        # calls_per_minute when a tool has no override.
        self.per_tool_rpm: dict[str, int] = {}
        self.logger = logger.bind(policy="rate_limiter")

        # Storage: {key -> [(timestamp, count)]}
        self._minute_buckets: dict[str, list] = defaultdict(list)
        self._hour_buckets: dict[str, list] = defaultdict(list)

    def check_and_record(self, tool_name: str, run_id: str) -> tuple[bool, str]:
        """
        Check if call is allowed and record it.

        Args:
            tool_name: Name of tool being called
            run_id: Current run ID

        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        now = datetime.now(UTC)

        # Per-tool per-minute limit. Use DSL override if declared, else the
        # global default.
        tool_limit = self.per_tool_rpm.get(tool_name, self.calls_per_minute)
        tool_key = f"tool:{tool_name}"
        if not self._check_bucket(
            self._minute_buckets[tool_key], now, timedelta(minutes=1), tool_limit
        ):
            reason = f"Tool '{tool_name}' exceeded {tool_limit} calls/minute"
            self.logger.warning(
                "rate_limit_exceeded",
                tool=tool_name,
                run_id=run_id,
                limit_type="per_minute",
                limit=tool_limit,
            )
            return False, reason

        # Check per-workflow per-hour limit
        run_key = f"run:{run_id}"
        if not self._check_bucket(
            self._hour_buckets[run_key], now, timedelta(hours=1), self.calls_per_hour
        ):
            reason = f"Workflow exceeded {self.calls_per_hour} calls/hour"
            self.logger.warning(
                "rate_limit_exceeded",
                tool=tool_name,
                run_id=run_id,
                limit_type="per_hour",
                limit=self.calls_per_hour,
            )
            return False, reason

        # Record the call
        self._minute_buckets[tool_key].append(now)
        self._hour_buckets[run_key].append(now)

        self.logger.debug("rate_limit_check_passed", tool=tool_name, run_id=run_id)

        return True, "ok"

    def _check_bucket(self, bucket: list, now: datetime, window: timedelta, limit: int) -> bool:
        """
        Check if bucket has capacity.

        Args:
            bucket: List of timestamps
            now: Current time
            window: Time window
            limit: Max calls in window

        Returns:
            True if call allowed
        """
        # Remove expired entries
        cutoff = now - window
        bucket[:] = [ts for ts in bucket if ts > cutoff]

        # Check if under limit
        return len(bucket) < limit

    def get_stats(self, run_id: str) -> dict[str, int]:
        """
        Get rate limit stats for a run.

        Args:
            run_id: Run ID

        Returns:
            Dict with current usage
        """
        now = datetime.now(UTC)
        run_key = f"run:{run_id}"

        # Clean and count hour bucket
        hour_cutoff = now - timedelta(hours=1)
        hour_bucket = self._hour_buckets[run_key]
        hour_bucket[:] = [ts for ts in hour_bucket if ts > hour_cutoff]

        return {
            "calls_last_hour": len(hour_bucket),
            "limit_per_hour": self.calls_per_hour,
            "remaining_calls": max(0, self.calls_per_hour - len(hour_bucket)),
        }

    def reset(self, run_id: str) -> None:
        """Reset rate limits for a run"""
        run_key = f"run:{run_id}"
        if run_key in self._hour_buckets:
            del self._hour_buckets[run_key]
        self.logger.info("rate_limit_reset", run_id=run_id)
