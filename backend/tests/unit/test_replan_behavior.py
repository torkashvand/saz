"""Tests for ReplanRequired exception behavior in executor."""

from saz.agents.schemas import Critique, Verdict
from saz.engine.executor import ReplanRequired


def test_replan_exception_carries_critique():
    critique = Critique(
        verdict=Verdict.REPLAN,
        reasoning="Step output does not match expected format",
        issues=["format_mismatch"],
        safety_flags=[],
        suggestions={"next_action": "retry_with_different_params"},
        confidence=0.7,
    )

    exc = ReplanRequired("Replanning required: format mismatch", critique=critique)

    assert str(exc) == "Replanning required: format mismatch"
    assert exc.critique.verdict == Verdict.REPLAN
    assert exc.critique.reasoning == "Step output does not match expected format"
    assert exc.critique.confidence == 0.7


def test_replan_is_exception():
    """ReplanRequired is a standard Exception subclass."""
    critique = Critique(
        verdict=Verdict.REPLAN,
        reasoning="test",
        issues=[],
        safety_flags=[],
        suggestions={},
        confidence=0.5,
    )
    exc = ReplanRequired("test", critique=critique)
    assert isinstance(exc, Exception)


def test_replan_caught_separately_from_generic_exception():
    """ReplanRequired can be caught independently from other exceptions."""
    critique = Critique(
        verdict=Verdict.REPLAN,
        reasoning="test",
        issues=[],
        safety_flags=[],
        suggestions={},
        confidence=0.5,
    )

    caught_replan = False
    try:
        raise ReplanRequired("test", critique=critique)
    except ReplanRequired:
        caught_replan = True
    except Exception:
        pass

    assert caught_replan
