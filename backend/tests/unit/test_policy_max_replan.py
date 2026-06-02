"""Tests for max_replan_attempts policy enforcement.

Proves: PolicyEngine reads max_replan_attempts from DSL and makes it available
to the executor for bounding the replanning loop.
"""

from saz.policies.policy_engine import PolicyEngine


def test_default_max_replan_attempts():
    """Default max_replan_attempts is 3."""
    engine = PolicyEngine()
    assert engine.max_replan_attempts == 3


def test_initialize_from_dsl_sets_max_replan():
    """initialize_from_dsl reads max_replan_attempts from policies dict."""
    engine = PolicyEngine()
    engine.initialize_from_dsl(
        "run-1",
        {
            "budget_usd": 1.0,
            "max_replan_attempts": 5,
        },
    )
    assert engine.max_replan_attempts == 5


def test_initialize_from_dsl_default_when_missing():
    """When max_replan_attempts not in DSL, default is used."""
    engine = PolicyEngine()
    engine.initialize_from_dsl(
        "run-1",
        {
            "budget_usd": 1.0,
        },
    )
    assert engine.max_replan_attempts == 3


def test_initialize_from_dsl_zero_disables_replan():
    """Setting max_replan_attempts to 0 means no replanning."""
    engine = PolicyEngine()
    engine.initialize_from_dsl(
        "run-1",
        {
            "max_replan_attempts": 0,
        },
    )
    assert engine.max_replan_attempts == 0


def test_max_replan_from_compiled_dsl():
    """max_replan_attempts flows through from compiled DSL format."""
    engine = PolicyEngine()
    # Simulates what the compiler produces
    compiled_policies = {
        "budget_usd": 1.0,
        "max_tokens": 100000,
        "max_steps": 50,
        "max_time_seconds": 300,
        "max_replan_attempts": 2,
        "pii": {"allow": False},
    }
    engine.initialize_from_dsl("run-1", compiled_policies)
    assert engine.max_replan_attempts == 2


def test_budget_sub_limits_settable_from_dsl():
    """max_tokens / max_steps / max_time_seconds are read from policies and
    applied to the budget tracker (previously hard-coded)."""
    engine = PolicyEngine()
    engine.initialize_from_dsl(
        "run-1",
        {
            "budget_usd": 2.0,
            "max_tokens": 500,
            "max_steps": 7,
            "max_time_seconds": 120,
        },
    )
    assert engine.budget_tracker.max_cost_usd == 2.0
    assert engine.budget_tracker.max_tokens == 500
    assert engine.budget_tracker.max_steps == 7
    assert engine.budget_tracker.max_time_seconds == 120


def test_budget_sub_limits_default_when_missing():
    """Defaults are preserved when the DSL omits the limits."""
    engine = PolicyEngine()
    defaults = (
        engine.budget_tracker.max_tokens,
        engine.budget_tracker.max_steps,
        engine.budget_tracker.max_time_seconds,
    )
    engine.initialize_from_dsl("run-1", {"budget_usd": 1.0})
    assert (
        engine.budget_tracker.max_tokens,
        engine.budget_tracker.max_steps,
        engine.budget_tracker.max_time_seconds,
    ) == defaults
