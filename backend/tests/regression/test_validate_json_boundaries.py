"""Boundary tests for ``AIOperationsRunner._validate_json``.

This validator is what stops the AI from returning structurally-wrong
output and the executor mistakenly treating it as success. Mutation
testing on it is high-value — a flipped `not isinstance(x, T)` or a
swapped `==` / `!=` would let bad output through. These tests are
written so that the most natural mutations of the validator are caught.
"""

import pytest

from saz.agents.ai_ops import AIOperationsRunner
from tests.conftest import MockLLMPort


@pytest.fixture
def runner() -> AIOperationsRunner:
    return AIOperationsRunner(llm_port=MockLLMPort())


def test_object_with_all_required_fields_accepted(runner):
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    }
    runner._validate_json({"a": "ok", "b": 1}, schema)  # must not raise


def test_missing_required_field_rejected(runner):
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    }
    with pytest.raises(ValueError, match="Missing required field: b"):
        runner._validate_json({"a": "ok"}, schema)


def test_extra_key_rejected_when_additional_properties_false(runner):
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
    }
    with pytest.raises(ValueError, match="Unexpected extra fields"):
        runner._validate_json({"a": "ok", "rogue": 1}, schema)


def test_extra_key_allowed_when_additional_properties_true(runner):
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
        "additionalProperties": True,
    }
    runner._validate_json({"a": "ok", "extra": "fine"}, schema)


def test_wrong_type_string_field_rejected(runner):
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
    }
    with pytest.raises(ValueError, match="must be string"):
        runner._validate_json({"a": 123}, schema)


def test_integer_field_rejects_bool(runner):
    """bool subclasses int in Python — the validator must NOT silently
    accept True/False where integer is required."""
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
    }
    with pytest.raises(ValueError, match="must be integer"):
        runner._validate_json({"n": True}, schema)


def test_number_field_rejects_bool(runner):
    schema = {
        "type": "object",
        "properties": {"n": {"type": "number"}},
        "required": ["n"],
    }
    with pytest.raises(ValueError, match="must be number"):
        runner._validate_json({"n": False}, schema)


def test_number_field_accepts_int_and_float(runner):
    schema = {
        "type": "object",
        "properties": {"n": {"type": "number"}},
        "required": ["n"],
    }
    runner._validate_json({"n": 1}, schema)
    runner._validate_json({"n": 1.5}, schema)


def test_boolean_field_rejects_int(runner):
    schema = {
        "type": "object",
        "properties": {"b": {"type": "boolean"}},
        "required": ["b"],
    }
    with pytest.raises(ValueError, match="must be boolean"):
        runner._validate_json({"b": 1}, schema)


def test_array_field_rejects_tuple_like_data(runner):
    schema = {
        "type": "object",
        "properties": {"xs": {"type": "array"}},
        "required": ["xs"],
    }
    with pytest.raises(ValueError, match="must be array"):
        runner._validate_json({"xs": "not a list"}, schema)


def test_null_required_field_rejected_when_type_constrained(runner):
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
    }
    with pytest.raises(ValueError, match="(is null|null)"):
        runner._validate_json({"a": None}, schema)


def test_optional_field_may_be_omitted(runner):
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        "required": ["a"],
    }
    runner._validate_json({"a": "x"}, schema)  # b missing — fine


def test_top_level_object_required_actually_object(runner):
    schema = {"type": "object", "properties": {}, "required": []}
    with pytest.raises(ValueError, match="Expected object"):
        runner._validate_json("not a dict", schema)
