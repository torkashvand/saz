"""Behavioral tests for BudgetTracker.

BudgetTracker enforces autonomy budget limits on tokens, cost, steps, and
elapsed time. Failure-mode coverage: when a limit is reached, the policy
engine must refuse to authorise more tool calls, otherwise an autonomous
run could spend through the cap before any guard fires.
"""

from datetime import UTC, datetime, timedelta

import pytest

from saz.policies.budget_tracker import BudgetTracker


@pytest.fixture
def tracker() -> BudgetTracker:
    return BudgetTracker(
        max_tokens=1000,
        max_cost_usd=1.0,
        max_steps=5,
        max_time_seconds=60,
    )


# --------------------------- Tokens ---------------------------


def test_budget_tracker_allows_below_token_limit(tracker: BudgetTracker) -> None:
    tracker.initialize_run("r1")
    tracker.record_tokens("r1", 999)
    ok, reason = tracker.check_budget("r1")
    assert ok is True
    assert reason is None


def test_budget_tracker_blocks_at_exact_token_limit(tracker: BudgetTracker) -> None:
    """Reaching the cap exactly counts as exceeded (>= max)."""
    tracker.initialize_run("r1")
    tracker.record_tokens("r1", 1000)
    ok, reason = tracker.check_budget("r1")
    assert ok is False
    assert reason is not None and "Token budget exceeded" in reason


def test_budget_tracker_blocks_over_token_limit(tracker: BudgetTracker) -> None:
    tracker.initialize_run("r1")
    tracker.record_tokens("r1", 1500)
    ok, reason = tracker.check_budget("r1")
    assert ok is False
    assert reason is not None and "Token budget exceeded: 1500/1000" in reason


# --------------------------- Cost ---------------------------


def test_budget_tracker_allows_below_cost_limit(tracker: BudgetTracker) -> None:
    tracker.initialize_run("r1")
    tracker.record_cost("r1", 0.99)
    ok, reason = tracker.check_budget("r1")
    assert ok is True
    assert reason is None


def test_budget_tracker_blocks_at_exact_cost_limit(tracker: BudgetTracker) -> None:
    tracker.initialize_run("r1")
    tracker.record_cost("r1", 1.0)
    ok, reason = tracker.check_budget("r1")
    assert ok is False
    assert reason is not None and "Cost budget exceeded" in reason


def test_budget_tracker_blocks_over_cost_limit(tracker: BudgetTracker) -> None:
    tracker.initialize_run("r1")
    tracker.record_cost("r1", 1.25)
    ok, reason = tracker.check_budget("r1")
    assert ok is False
    assert reason is not None and "Cost budget exceeded" in reason


# --------------------------- Steps ---------------------------


def test_budget_tracker_allows_below_step_limit(tracker: BudgetTracker) -> None:
    tracker.initialize_run("r1")
    for _ in range(4):
        tracker.record_step("r1")
    ok, _ = tracker.check_budget("r1")
    assert ok is True


def test_budget_tracker_blocks_at_exact_step_limit(tracker: BudgetTracker) -> None:
    tracker.initialize_run("r1")
    for _ in range(5):
        tracker.record_step("r1")
    ok, reason = tracker.check_budget("r1")
    assert ok is False
    assert reason is not None and "Step budget exceeded: 5/5" in reason


# --------------------------- Time ---------------------------


def test_budget_tracker_blocks_when_time_elapsed(tracker: BudgetTracker) -> None:
    tracker.initialize_run("r1")
    # Rewind start_time so elapsed_seconds >= max_time_seconds
    tracker._budgets["r1"]["start_time"] = datetime.now(UTC) - timedelta(seconds=120)
    ok, reason = tracker.check_budget("r1")
    assert ok is False
    assert reason is not None and "Time budget exceeded" in reason


# --------------------------- Implicit init / accumulation ---------------------------


def test_budget_tracker_implicit_init_on_first_record(tracker: BudgetTracker) -> None:
    """record_tokens/cost/step should auto-initialize the per-run budget so
    callers do not have to remember to call initialize_run() first."""
    tracker.record_tokens("auto", 100)
    tracker.record_cost("auto", 0.10)
    tracker.record_step("auto")
    stats = tracker.get_stats("auto")
    assert stats is not None
    assert stats["tokens_used"] == 100
    assert stats["cost_usd"] == 0.10
    assert stats["steps_executed"] == 1


def test_budget_tracker_accumulates_multiple_updates(tracker: BudgetTracker) -> None:
    tracker.initialize_run("r1")
    tracker.record_tokens("r1", 100)
    tracker.record_tokens("r1", 250)
    tracker.record_cost("r1", 0.25)
    tracker.record_cost("r1", 0.10)
    tracker.record_step("r1")
    tracker.record_step("r1")

    stats = tracker.get_stats("r1")
    assert stats is not None
    assert stats["tokens_used"] == 350
    assert stats["cost_usd"] == pytest.approx(0.35)
    assert stats["steps_executed"] == 2


# --------------------------- get_remaining / get_stats / reset ---------------------------


def test_budget_tracker_get_remaining_reports_usage_breakdown(tracker: BudgetTracker) -> None:
    tracker.initialize_run("r1")
    tracker.record_tokens("r1", 200)
    tracker.record_cost("r1", 0.25)
    tracker.record_step("r1")

    remaining = tracker.get_remaining("r1")

    assert remaining["tokens"]["used"] == 200
    assert remaining["tokens"]["remaining"] == 800
    assert remaining["tokens"]["percentage"] == pytest.approx(20.0)

    assert remaining["cost"]["used"] == pytest.approx(0.25)
    assert remaining["cost"]["remaining"] == pytest.approx(0.75)

    assert remaining["steps"]["used"] == 1
    assert remaining["steps"]["remaining"] == 4

    assert remaining["time"]["max_seconds"] == 60
    assert remaining["time"]["used_seconds"] >= 0


def test_budget_tracker_get_remaining_clamps_at_zero_when_over(tracker: BudgetTracker) -> None:
    """When usage exceeds the limit, remaining must not be negative — the
    UI/policy engine relies on this being clamped at zero."""
    tracker.initialize_run("r1")
    tracker.record_tokens("r1", 2000)
    tracker.record_cost("r1", 5.0)
    for _ in range(10):
        tracker.record_step("r1")

    remaining = tracker.get_remaining("r1")
    assert remaining["tokens"]["remaining"] == 0
    assert remaining["cost"]["remaining"] == 0
    assert remaining["steps"]["remaining"] == 0


def test_budget_tracker_get_stats_returns_none_for_unknown_run(tracker: BudgetTracker) -> None:
    """get_stats must NOT auto-initialize — it's a read-only probe."""
    assert tracker.get_stats("never-seen") is None


def test_budget_tracker_reset_clears_usage(tracker: BudgetTracker) -> None:
    tracker.initialize_run("r1")
    tracker.record_tokens("r1", 100)
    tracker.reset("r1")
    assert tracker.get_stats("r1") is None


def test_budget_tracker_reset_is_safe_for_unknown_run(tracker: BudgetTracker) -> None:
    # Idempotent: resetting a run that was never initialized must not raise.
    tracker.reset("never-seen")
    assert tracker.get_stats("never-seen") is None


def test_negative_cost_is_clamped_and_cannot_inflate_remaining(tracker: BudgetTracker) -> None:
    """A negative cost must not credit the budget back: remaining can only
    shrink. Otherwise a bogus negative usage report reopens a spent budget."""
    tracker.initialize_run("rneg")
    tracker.record_cost("rneg", 0.5)
    tracker.record_cost("rneg", -10.0)  # clamped to 0
    rem = tracker.get_remaining("rneg")
    assert rem["cost"]["used"] == pytest.approx(0.5)
    assert rem["cost"]["remaining"] <= tracker.max_cost_usd


def test_negative_tokens_is_clamped_and_cannot_inflate_remaining(tracker: BudgetTracker) -> None:
    tracker.initialize_run("rneg2")
    tracker.record_tokens("rneg2", 100)
    tracker.record_tokens("rneg2", -1000)  # clamped to 0
    rem = tracker.get_remaining("rneg2")
    assert rem["tokens"]["used"] == 100
    assert rem["tokens"]["remaining"] <= tracker.max_tokens
