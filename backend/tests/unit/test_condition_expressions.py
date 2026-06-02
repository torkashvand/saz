"""Unit tests for the safe boolean condition evaluator."""

from collections.abc import Callable
from typing import Any

import pytest

from saz.engine.expressions import (
    ConditionError,
    coerce_bool,
    evaluate_condition,
    render_condition,
)


def _resolver(values: dict[str, Any]) -> Callable[[str], Any]:
    def resolve(token: str) -> Any:
        return values.get(token)

    return resolve


def _ev(expr: str, values: dict[str, Any] | None = None) -> bool:
    return evaluate_condition(expr, _resolver(values or {}))


# --- literals & booleans ---


def test_true_literal() -> None:
    assert _ev("true") is True


def test_false_literal() -> None:
    assert _ev("false") is False


def test_direct_bool_passthrough() -> None:
    assert evaluate_condition(True, _resolver({})) is True
    assert evaluate_condition(False, _resolver({})) is False


def test_none_is_false() -> None:
    assert evaluate_condition(None, _resolver({})) is False


# --- the placeholder bug must be gone ---


def test_arbitrary_word_is_not_an_operator_expression() -> None:
    # A bare quoted string is truthy, but a comparison decides correctly.
    assert _ev("'approved' == 'approved'") is True
    assert _ev("'approved' == 'rejected'") is False


# --- numeric comparisons ---


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("5 > 3", True),
        ("5 < 3", False),
        ("5 >= 5", True),
        ("4 <= 3", False),
        ("5 == 5", True),
        ("5 != 4", True),
        ("0 > 0", False),
    ],
)
def test_numeric_comparisons(expr: str, expected: bool) -> None:
    assert _ev(expr) is expected


# --- string comparisons ---


def test_string_equality() -> None:
    assert _ev('"high" == "high"') is True
    assert _ev('"low" == "high"') is False


# --- boolean operators ---


def test_and_true() -> None:
    assert _ev("5 > 0 && 5 < 5000") is True


def test_and_false() -> None:
    assert _ev("5 > 0 && 10000 < 5000") is False


def test_or() -> None:
    assert _ev("5 < 0 || 3 == 3") is True


def test_not() -> None:
    assert _ev("!(5 < 0)") is True
    assert _ev("!(3 == 3)") is False


def test_parentheses_precedence() -> None:
    assert _ev("(1 == 1 || 2 == 3) && 4 == 4") is True
    assert _ev("1 == 1 || 2 == 3 && 4 == 5") is True


# --- reference resolution ---


def test_form_reference_numeric() -> None:
    values = {"$form.budget": 3000, "$step('x').risk": "high"}
    expr = "$form.budget > 0 && $form.budget < 5000 " "&& $step('x').risk == 'high'"
    assert _ev(expr, values) is True


def test_form_reference_false_branch() -> None:
    values = {"$form.budget": 9000, "$step('x').risk": "high"}
    expr = "$form.budget > 0 && $form.budget < 5000 && $step('x').risk == 'high'"
    assert _ev(expr, values) is False


def test_braces_are_stripped() -> None:
    values = {"$form.budget": 100}
    assert _ev("{{ $form.budget > 50 }}", values) is True


def test_missing_reference_is_none() -> None:
    assert _ev("$form.unknown == 'x'") is False
    assert _ev("$form.unknown", {}) is False


# --- failure modes (fail closed) ---


def test_malformed_raises() -> None:
    with pytest.raises(ConditionError):
        _ev("5 > > 3")


def test_unbalanced_parens_raises() -> None:
    with pytest.raises(ConditionError):
        _ev("(5 > 3")


def test_unexpected_character_raises() -> None:
    with pytest.raises(ConditionError):
        _ev("5 @ 3")


def test_empty_raises() -> None:
    with pytest.raises(ConditionError):
        _ev("   ")


# --- coerce_bool / render ---


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        (False, False),
        (None, False),
        (0, False),
        (1, True),
        ("", False),
        ("no", False),
        ("yes", True),
        ([], False),
        ([1], True),
        ({}, False),
    ],
)
def test_coerce_bool(value: object, expected: bool) -> None:
    assert coerce_bool(value) is expected


def test_render_condition_substitutes_values() -> None:
    values = {"$form.budget": 3000}
    rendered = render_condition("{{ $form.budget < 5000 }}", _resolver(values))
    assert rendered == "3000 < 5000"
