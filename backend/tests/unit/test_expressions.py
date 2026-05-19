"""Behavioral tests for saz.engine.expressions.

`engine/expressions.py` ships two layers:

  * ``ExpressionEngine`` / ``resolve_expressions`` — a template resolver
    with helper functions (coalesce, toInt, toString, ...). Used as a
    standalone deterministic expression engine.

  * ``evaluate_expression(value, context)`` — the truthiness adapter used
    by ``WorkflowExecutor`` when deciding whether a ``condition`` step
    skips or runs. The executor first resolves variables via the
    ``TemplateContext`` (in ``engine/templating.py``) and then passes the
    *resolved* value here.

The two layers have different APIs and different semantics; this test
file covers both.
"""

import pytest

from saz.engine.expressions import (
    ExpressionEngine,
    evaluate_expression,
    resolve_expressions,
)

# --------------------------- ExpressionEngine: $form ---------------------------


def test_engine_resolves_form_value_with_typed_passthrough() -> None:
    """A single-expression template must return the raw typed value, not stringify."""
    engine = ExpressionEngine(form_data={"count": 7}, step_outputs={})
    assert engine.resolve("{{ $form.count }}") == 7


def test_engine_resolves_nested_form_path() -> None:
    engine = ExpressionEngine(
        form_data={"user": {"profile": {"email": "a@b.com"}}},
        step_outputs={},
    )
    assert engine.resolve("{{ $form.user.profile.email }}") == "a@b.com"


def test_engine_returns_none_for_missing_form_field() -> None:
    engine = ExpressionEngine(form_data={"a": 1}, step_outputs={})
    # Single-expr resolution returns the typed value, which is None.
    assert engine.resolve("{{ $form.missing }}") is None


def test_engine_interpolates_in_mixed_string() -> None:
    engine = ExpressionEngine(form_data={"name": "alice"}, step_outputs={})
    assert engine.resolve("Hello {{ $form.name }}!") == "Hello alice!"


def test_engine_interpolates_none_as_empty_in_mixed_string() -> None:
    engine = ExpressionEngine(form_data={}, step_outputs={})
    assert engine.resolve("X={{ $form.missing }};") == "X=;"


# --------------------------- ExpressionEngine: $step ---------------------------


def test_engine_resolves_step_output_full_dict_when_no_field() -> None:
    """``{{ $step('id') }}`` returns the entire step output dict (typed)."""
    engine = ExpressionEngine(
        form_data={},
        step_outputs={"plan": {"status": "ok", "items": [1, 2]}},
    )
    out = engine.resolve("{{ $step('plan') }}")
    assert out == {"status": "ok", "items": [1, 2]}


def test_engine_resolves_step_output_field() -> None:
    engine = ExpressionEngine(
        form_data={},
        step_outputs={"plan": {"status": "ok"}},
    )
    assert engine.resolve("{{ $step('plan').status }}") == "ok"


def test_engine_missing_step_id_returns_empty_dict_for_full_ref() -> None:
    engine = ExpressionEngine(form_data={}, step_outputs={})
    # Implementation falls back to ``self.step_outputs.get(step_id, {})``
    # — full ref returns {} when missing.
    assert engine.resolve("{{ $step('missing') }}") == {}


def test_engine_missing_step_field_returns_none() -> None:
    engine = ExpressionEngine(form_data={}, step_outputs={"a": {"x": 1}})
    assert engine.resolve("{{ $step('a').y }}") is None


# --------------------------- ExpressionEngine: $env / $secret ---------------------------


def test_engine_resolves_env_with_injected_resolver() -> None:
    engine = ExpressionEngine(
        form_data={},
        step_outputs={},
        env_resolver=lambda name: {"FOO": "bar"}.get(name, ""),
    )
    assert engine.resolve("{{ $env('FOO') }}") == "bar"


def test_engine_resolves_env_missing_to_empty_string() -> None:
    engine = ExpressionEngine(
        form_data={},
        step_outputs={},
        env_resolver=lambda _name: "",
    )
    # The implementation returns "" when env_resolver returns falsy.
    assert engine.resolve("{{ $env('MISSING') }}") == ""


def test_engine_resolves_secret_with_injected_resolver() -> None:
    engine = ExpressionEngine(
        form_data={},
        step_outputs={},
        secrets_resolver=lambda name: {"API_KEY": "shhh"}.get(name, ""),
    )
    assert engine.resolve("{{ $secret('API_KEY') }}") == "shhh"


# --------------------------- ExpressionEngine: helpers ---------------------------


def test_engine_helper_coalesce_returns_first_non_null() -> None:
    engine = ExpressionEngine(form_data={}, step_outputs={})
    # _parse_args splits by comma — first arg is null (None), second is literal "x".
    assert engine.resolve("{{ coalesce(null, 'x') }}") == "x"


def test_engine_helper_to_int_handles_invalid() -> None:
    engine = ExpressionEngine(form_data={}, step_outputs={})
    assert engine.resolve("{{ toInt('42') }}") == 42
    assert engine.resolve("{{ toInt('abc') }}") == 0


def test_engine_helper_lower_and_upper() -> None:
    engine = ExpressionEngine(form_data={}, step_outputs={})
    assert engine.resolve("{{ lower('ABC') }}") == "abc"
    assert engine.resolve("{{ upper('abc') }}") == "ABC"


def test_engine_helper_len_on_string() -> None:
    engine = ExpressionEngine(form_data={}, step_outputs={})
    assert engine.resolve("{{ len('abcd') }}") == 4


def test_engine_helper_to_bool_truthy_strings() -> None:
    engine = ExpressionEngine(form_data={}, step_outputs={})
    assert engine.resolve("{{ toBool('true') }}") is True
    assert engine.resolve("{{ toBool('yes') }}") is True
    assert engine.resolve("{{ toBool('no') }}") is False


def test_engine_helper_to_string() -> None:
    engine = ExpressionEngine(form_data={"n": 42}, step_outputs={})
    # Helper call on a single literal arg
    assert engine.resolve("{{ toString(42) }}") == "42"


# --------------------------- ExpressionEngine: literals ---------------------------


def test_engine_literal_integer_and_quoted_strings_and_booleans() -> None:
    engine = ExpressionEngine(form_data={}, step_outputs={})
    assert engine.resolve("{{ 42 }}") == 42
    assert engine.resolve("{{ 'hello' }}") == "hello"
    assert engine.resolve('{{ "hi" }}') == "hi"
    assert engine.resolve("{{ true }}") is True
    assert engine.resolve("{{ false }}") is False
    assert engine.resolve("{{ null }}") is None


# --------------------------- ExpressionEngine: nested resolution ---------------------------


def test_engine_resolves_nested_dict_and_list() -> None:
    engine = ExpressionEngine(
        form_data={"name": "alice", "n": 3},
        step_outputs={"compute": {"value": 99}},
    )
    template = {
        "greeting": "Hello {{ $form.name }}",
        "items": [
            "{{ $form.n }}",
            "{{ $step('compute').value }}",
        ],
        "nested": {"who": "{{ $form.name }}"},
    }
    out = engine.resolve(template)
    assert out == {
        "greeting": "Hello alice",
        "items": [3, 99],
        "nested": {"who": "alice"},
    }


def test_engine_passes_through_primitives() -> None:
    engine = ExpressionEngine(form_data={}, step_outputs={})
    assert engine.resolve(7) == 7
    assert engine.resolve(None) is None
    assert engine.resolve(True) is True


# --------------------------- ExpressionEngine: failure paths ---------------------------


def test_engine_returns_original_template_for_unknown_helper_in_mixed_string() -> None:
    """An unknown identifier inside a mixed-string template falls back to the
    raw literal — the substitution must not crash the executor."""
    engine = ExpressionEngine(form_data={}, step_outputs={})
    # In a mixed string, a totally unknown expression returns itself.
    out = engine.resolve("before {{ $weird.stuff }} after")
    assert "before " in out
    assert "after" in out


def test_engine_resolve_expressions_convenience_function() -> None:
    """The module-level ``resolve_expressions`` helper must mirror the class API."""
    out = resolve_expressions(
        template="Hello {{ $form.name }}",
        form_data={"name": "bob"},
        step_outputs={},
    )
    assert out == "Hello bob"


# --------------------------- evaluate_expression: condition step gate ---------------------------


def test_evaluate_expression_returns_bool_directly() -> None:
    assert evaluate_expression(True, {}) is True
    assert evaluate_expression(False, {}) is False


@pytest.mark.parametrize("value", ["true", "TRUE", "True", "1", "yes", "YES"])
def test_evaluate_expression_truthy_strings(value: str) -> None:
    assert evaluate_expression(value, {}) is True


@pytest.mark.parametrize("value", ["false", "0", "no", "", "  "])
def test_evaluate_expression_falsy_strings(value: str) -> None:
    assert evaluate_expression(value, {}) is False


def test_evaluate_expression_treats_arbitrary_string_as_truthy() -> None:
    # Per the implementation, a non-empty unrecognised string is truthy.
    assert evaluate_expression("approved", {}) is True


@pytest.mark.parametrize(
    "value,expected", [(0, False), (1, True), (-1, True), (0.0, False), (3.14, True)]
)
def test_evaluate_expression_numeric(value, expected) -> None:
    assert evaluate_expression(value, {}) is expected


def test_evaluate_expression_collections() -> None:
    assert evaluate_expression({}, {}) is False
    assert evaluate_expression([], {}) is False
    assert evaluate_expression({"a": 1}, {}) is True
    assert evaluate_expression([1], {}) is True


def test_evaluate_expression_none_is_false() -> None:
    assert evaluate_expression(None, {}) is False
