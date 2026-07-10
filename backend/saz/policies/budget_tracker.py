"""Budget Tracker - Tracks and enforces autonomy budget limits."""

from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class BudgetTracker:
    """
    Tracks autonomy budget consumption.

    Enforces limits on:
    - Total tokens (LLM input + output)
    - Total cost (USD)
    - Number of workflow steps
    - Execution time
    """

    def __init__(
        self,
        max_tokens: int = 100000,
        max_cost_usd: float = 10.0,
        max_steps: int = 50,
        max_time_seconds: int = 3600,
    ):
        self.max_tokens = max_tokens
        self.max_cost_usd = max_cost_usd
        self.max_steps = max_steps
        self.max_time_seconds = max_time_seconds
        self.logger = logger.bind(policy="budget_tracker")

        # Per-run tracking
        self._budgets: dict[str, dict] = {}

    def initialize_run(self, run_id: str) -> None:
        """
        Initialize budget tracking for a run.

        Args:
            run_id: Run ID
        """
        self._budgets[run_id] = {
            "tokens_used": 0,
            "cost_usd": 0.0,
            "steps_executed": 0,
            "start_time": datetime.now(UTC),
            "last_updated": datetime.now(UTC),
        }

        self.logger.info(
            "budget_initialized",
            run_id=run_id,
            max_tokens=self.max_tokens,
            max_cost_usd=self.max_cost_usd,
            max_steps=self.max_steps,
        )

    def seed_usage(self, run_id: str, tokens: int, cost_usd: float, steps: int) -> None:
        """Carry usage persisted by previous execution segments into this
        (fresh, in-memory) tracker.

        Budgets are per run, not per segment: resume after suspension and
        same-run retry both build a new tracker, and without replaying prior
        spend a capped run gets a full fresh budget every segment.
        """
        if run_id not in self._budgets:
            self.initialize_run(run_id)
        budget = self._budgets[run_id]
        budget["tokens_used"] += max(0, tokens)
        budget["cost_usd"] += max(0.0, cost_usd)
        budget["steps_executed"] += max(0, steps)
        budget["last_updated"] = datetime.now(UTC)

        self.logger.info(
            "budget_seeded_from_prior_segments",
            run_id=run_id,
            tokens=tokens,
            cost_usd=cost_usd,
            steps=steps,
        )

    def record_tokens(self, run_id: str, tokens: int) -> None:
        """
        Record token usage.

        Args:
            run_id: Run ID
            tokens: Number of tokens used
        """
        if run_id not in self._budgets:
            self.initialize_run(run_id)

        # Clamp negative usage: a bogus negative report must never credit the
        # budget back and reopen a spent cap.
        self._budgets[run_id]["tokens_used"] += max(0, tokens)
        self._budgets[run_id]["last_updated"] = datetime.now(UTC)

        self.logger.debug(
            "tokens_recorded",
            run_id=run_id,
            tokens=tokens,
            total=self._budgets[run_id]["tokens_used"],
        )

    def record_cost(self, run_id: str, cost_usd: float) -> None:
        """
        Record cost.

        Args:
            run_id: Run ID
            cost_usd: Cost in USD
        """
        if run_id not in self._budgets:
            self.initialize_run(run_id)

        # Clamp negative usage: a bogus negative report must never credit the
        # budget back and reopen a spent cap.
        self._budgets[run_id]["cost_usd"] += max(0.0, cost_usd)
        self._budgets[run_id]["last_updated"] = datetime.now(UTC)

        self.logger.debug(
            "cost_recorded",
            run_id=run_id,
            cost_usd=cost_usd,
            total=self._budgets[run_id]["cost_usd"],
        )

    def record_step(self, run_id: str) -> None:
        """
        Record step execution.

        Args:
            run_id: Run ID
        """
        if run_id not in self._budgets:
            self.initialize_run(run_id)

        self._budgets[run_id]["steps_executed"] += 1
        self._budgets[run_id]["last_updated"] = datetime.now(UTC)

        self.logger.debug(
            "step_recorded", run_id=run_id, total=self._budgets[run_id]["steps_executed"]
        )

    def check_budget(self, run_id: str) -> tuple[bool, str | None]:
        """
        Check if budget limits are exceeded.

        Args:
            run_id: Run ID

        Returns:
            Tuple of (within_budget: bool, exceeded_reason: Optional[str])
        """
        if run_id not in self._budgets:
            self.initialize_run(run_id)

        budget = self._budgets[run_id]

        # Check tokens
        if budget["tokens_used"] >= self.max_tokens:
            reason = f"Token budget exceeded: {budget['tokens_used']}/{self.max_tokens}"
            self.logger.warning("budget_exceeded", run_id=run_id, reason=reason)
            return False, reason

        # Check cost
        if budget["cost_usd"] >= self.max_cost_usd:
            reason = f"Cost budget exceeded: ${budget['cost_usd']:.2f}/${self.max_cost_usd:.2f}"
            self.logger.warning("budget_exceeded", run_id=run_id, reason=reason)
            return False, reason

        # Check steps
        if budget["steps_executed"] >= self.max_steps:
            reason = f"Step budget exceeded: {budget['steps_executed']}/{self.max_steps}"
            self.logger.warning("budget_exceeded", run_id=run_id, reason=reason)
            return False, reason

        # Check time
        elapsed_seconds = (datetime.now(UTC) - budget["start_time"]).total_seconds()
        if elapsed_seconds >= self.max_time_seconds:
            reason = f"Time budget exceeded: {elapsed_seconds:.0f}s/{self.max_time_seconds}s"
            self.logger.warning("budget_exceeded", run_id=run_id, reason=reason)
            return False, reason

        return True, None

    def get_remaining(self, run_id: str) -> dict[str, Any]:
        """
        Get remaining budget.

        Args:
            run_id: Run ID

        Returns:
            Dict with remaining budget
        """
        if run_id not in self._budgets:
            self.initialize_run(run_id)

        budget = self._budgets[run_id]
        elapsed_seconds = (datetime.now(UTC) - budget["start_time"]).total_seconds()

        def _pct(used: float, limit: float) -> float:
            # A zero (or negative) limit means "no headroom"; report 100% used
            # rather than dividing by zero.
            if limit <= 0:
                return 100.0
            return (used / limit) * 100

        return {
            "tokens": {
                "used": budget["tokens_used"],
                "max": self.max_tokens,
                "remaining": max(0, self.max_tokens - budget["tokens_used"]),
                "percentage": _pct(budget["tokens_used"], self.max_tokens),
            },
            "cost": {
                "used": budget["cost_usd"],
                "max": self.max_cost_usd,
                "remaining": max(0, self.max_cost_usd - budget["cost_usd"]),
                "percentage": _pct(budget["cost_usd"], self.max_cost_usd),
            },
            "steps": {
                "used": budget["steps_executed"],
                "max": self.max_steps,
                "remaining": max(0, self.max_steps - budget["steps_executed"]),
                "percentage": _pct(budget["steps_executed"], self.max_steps),
            },
            "time": {
                "used_seconds": elapsed_seconds,
                "max_seconds": self.max_time_seconds,
                "remaining_seconds": max(0, self.max_time_seconds - elapsed_seconds),
                "percentage": _pct(elapsed_seconds, self.max_time_seconds),
            },
        }

    def get_stats(self, run_id: str) -> dict | None:
        """Get budget stats for a run"""
        return self._budgets.get(run_id)

    def reset(self, run_id: str) -> None:
        """Reset budget for a run"""
        if run_id in self._budgets:
            del self._budgets[run_id]
        self.logger.info("budget_reset", run_id=run_id)
