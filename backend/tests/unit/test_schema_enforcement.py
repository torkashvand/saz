"""Tests for runtime schema enforcement in AI operations.

Two layers of tests:
1. Validator-level: proves _validate_json catches each bug class
2. Runtime-level: proves run_ai_op rejects/repairs malformed LLM output
   through the real AI-op path (mock LLM, real validator, real repair flow)

All tests are function-based per repo standard.
"""

import json

import pytest

from saz.agents.ai_ops import AI_OPS, AIOperationsRunner
from saz.agents.llm_port import LLMPort, LLMResponse

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Schema that mirrors a real ai.assess / incident extraction scenario.
# Has explicit properties, required fields, enums — no additionalProperties.
INCIDENT_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string"},
        "severity": {
            "type": "string",
            "enum": ["low", "medium", "high", "critical"],
        },
        "service": {"type": "string"},
        "impact_scope": {
            "type": "string",
            "enum": ["single_user", "organization", "external"],
        },
        "appears_known": {"type": "boolean"},
    },
    "required": ["category", "severity", "service"],
}

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["score"],
}


@pytest.fixture
def validate():
    """Get the validator method from AIOperationsRunner."""
    runner = AIOperationsRunner.__new__(AIOperationsRunner)
    return runner._validate_json


# ---------------------------------------------------------------------------
# Helper for runtime (end-to-end) AI-op tests
# ---------------------------------------------------------------------------


class _FixedLLM(LLMPort):
    """Minimal mock LLM that returns pre-set responses in sequence."""

    def __init__(self, *responses: str):
        self._responses = list(responses)
        self._idx = 0

    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> LLMResponse:
        content = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return LLMResponse(
            content=content,
            total_tokens=50,
            prompt_tokens=30,
            completion_tokens=20,
            model=model,
        )


def _make_runner(*llm_responses: str) -> AIOperationsRunner:
    """Create an AIOperationsRunner wired to a fixed-response LLM."""
    llm = _FixedLLM(*llm_responses)
    runner = AIOperationsRunner(llm_port=llm, default_model="test")
    return runner


# ===================================================================
# SECTION A — Wrong key names (the original real-world bug)
# ===================================================================


def test_wrong_case_keys_rejected_by_validator(validate):
    """Capitalized keys ('Category') instead of schema keys ('category')
    must be rejected — either as missing required or as unexpected extra."""
    data = {"Category": "network", "Severity": "high", "Service": "api"}
    with pytest.raises(ValueError):
        validate(data, INCIDENT_SCHEMA)


def test_human_readable_extra_keys_rejected(validate):
    """Extra human-readable keys alongside correct keys are rejected."""
    data = {
        "category": "network",
        "severity": "high",
        "service": "api",
        "Affected service or component": "api",  # hallucinated extra
    }
    with pytest.raises(ValueError, match="Unexpected extra fields"):
        validate(data, INCIDENT_SCHEMA)


def test_correct_keys_accepted(validate):
    data = {"category": "network", "severity": "high", "service": "api"}
    validate(data, INCIDENT_SCHEMA)  # should not raise


@pytest.mark.asyncio
async def test_runtime_rejects_wrong_key_names():
    """End-to-end: run_ai_op with wrong-cased keys triggers repair path.

    This is the exact regression test for the motivating real-world bug:
    ai.extract returned 'Category' instead of 'category' and the system
    silently accepted it.
    """
    wrong_output = json.dumps(
        {
            "Category": "network",
            "Severity": "high",
            "Service": "api-gateway",
        }
    )
    # Repair also returns wrong output — system should raise
    repair_output = json.dumps(
        {
            "Category": "network",
            "Severity": "high",
            "Service": "api-gateway",
        }
    )
    runner = _make_runner(wrong_output, repair_output)

    with pytest.raises(ValueError):
        await runner.run_ai_op(
            op_name="ai.assess",
            instruction="Classify incident",
            data={"text": "Server is down"},
            expected_schema=INCIDENT_SCHEMA,
        )


@pytest.mark.asyncio
async def test_runtime_repair_fixes_wrong_keys():
    """End-to-end: if repair produces correct keys, output is accepted."""
    wrong_output = json.dumps(
        {
            "Category": "network",
            "Severity": "high",
            "Service": "api-gateway",
        }
    )
    repaired_output = json.dumps(
        {
            "category": "network",
            "severity": "high",
            "service": "api-gateway",
        }
    )
    runner = _make_runner(wrong_output, repaired_output)

    result = await runner.run_ai_op(
        op_name="ai.assess",
        instruction="Classify incident",
        data={"text": "Server is down"},
        expected_schema=INCIDENT_SCHEMA,
    )
    assert result["output"]["category"] == "network"
    assert result["output"]["severity"] == "high"


# ===================================================================
# SECTION B — Extra hallucinated keys
# ===================================================================


def test_extra_keys_rejected_when_not_allowed(validate):
    """Schema without additionalProperties rejects extra keys."""
    data = {
        "category": "network",
        "severity": "high",
        "service": "api",
        "confidence": 0.95,  # not in schema
    }
    with pytest.raises(ValueError, match="Unexpected extra fields"):
        validate(data, INCIDENT_SCHEMA)


def test_additional_properties_true_allows_extras(validate):
    """ai.extract default schema has additionalProperties: true —
    extra keys are intentionally allowed for flexible extraction."""
    schema = AI_OPS["ai.extract"].default_expect_schema
    assert schema.get("additionalProperties") is True
    data = {"any_key": "value", "another": 123}
    validate(data, schema)  # should not raise


def test_additional_properties_false_is_default(validate):
    """Schemas without explicit additionalProperties default to rejecting extras."""
    # INCIDENT_SCHEMA has no additionalProperties key
    assert "additionalProperties" not in INCIDENT_SCHEMA
    data = {
        "category": "net",
        "severity": "low",
        "service": "api",
        "extra": "not allowed",
    }
    with pytest.raises(ValueError, match="Unexpected extra fields"):
        validate(data, INCIDENT_SCHEMA)


@pytest.mark.asyncio
async def test_runtime_rejects_extra_keys():
    """End-to-end: run_ai_op rejects output with hallucinated extra fields."""
    output_with_extras = json.dumps(
        {
            "result": "incident classified",
            "confidence": 0.9,
            "hallucinated_field": "should not be here",
        }
    )
    # Repair also fails
    runner = _make_runner(output_with_extras, output_with_extras)

    with pytest.raises(ValueError):
        await runner.run_ai_op(
            op_name="ai.assess",
            instruction="Classify incident",
            data={"text": "Server down"},
        )


# ===================================================================
# SECTION C — Missing and null required fields
# ===================================================================


def test_missing_required_field_rejected(validate):
    data = {"category": "network", "severity": "high"}  # missing "service"
    with pytest.raises(ValueError, match="Missing required field: service"):
        validate(data, INCIDENT_SCHEMA)


def test_null_required_field_rejected(validate):
    """Required fields cannot be null when typed as non-null."""
    data = {"category": None, "severity": "high", "service": "api"}
    with pytest.raises(ValueError, match="null"):
        validate(data, INCIDENT_SCHEMA)


def test_null_optional_typed_field_rejected(validate):
    """Optional means 'may be omitted,' not 'may be null.'
    A typed optional field set to null must be rejected."""
    data = {
        "category": "network",
        "severity": "high",
        "service": "api",
        "impact_scope": None,  # typed as string — null is not valid
    }
    with pytest.raises(ValueError, match="null"):
        validate(data, INCIDENT_SCHEMA)


def test_null_untyped_field_accepted(validate):
    """A field with no type constraint may be null."""
    schema = {
        "type": "object",
        "properties": {"meta": {}},  # no type specified
    }
    validate({"meta": None}, schema)  # should not raise


def test_omitted_optional_field_accepted(validate):
    """Optional fields may be omitted entirely."""
    data = {"category": "net", "severity": "low", "service": "api"}
    validate(data, INCIDENT_SCHEMA)  # should not raise


@pytest.mark.asyncio
async def test_runtime_rejects_missing_required():
    """End-to-end: run_ai_op rejects LLM output missing a required field."""
    # ai.assess requires "result" — omit it
    incomplete = json.dumps({"confidence": 0.5})
    runner = _make_runner(incomplete, incomplete)

    with pytest.raises(ValueError):
        await runner.run_ai_op(
            op_name="ai.assess",
            instruction="Classify",
            data={"text": "test"},
        )


# ===================================================================
# SECTION D — Enum violations
# ===================================================================


def test_invalid_enum_rejected(validate):
    data = {"category": "net", "severity": "urgent", "service": "api"}
    with pytest.raises(ValueError, match="Must be one of"):
        validate(data, INCIDENT_SCHEMA)


def test_wrong_case_enum_rejected(validate):
    data = {"category": "net", "severity": "High", "service": "api"}
    with pytest.raises(ValueError, match="Must be one of"):
        validate(data, INCIDENT_SCHEMA)


def test_valid_enum_accepted(validate):
    data = {"category": "net", "severity": "critical", "service": "api"}
    validate(data, INCIDENT_SCHEMA)  # should not raise


# ===================================================================
# SECTION E — Numeric type and bounds
# ===================================================================


def test_number_rejects_bool(validate):
    """bool must be rejected for 'number' fields (bool is subclass of int)."""
    with pytest.raises(ValueError, match="must be number"):
        validate({"score": True}, SCORE_SCHEMA)


def test_number_accepts_int(validate):
    validate({"score": 1}, SCORE_SCHEMA)


def test_number_accepts_float(validate):
    validate({"score": 0.75}, SCORE_SCHEMA)


def test_score_below_minimum_rejected(validate):
    with pytest.raises(ValueError, match="below minimum"):
        validate({"score": -0.1}, SCORE_SCHEMA)


def test_score_above_maximum_rejected(validate):
    with pytest.raises(ValueError, match="above maximum"):
        validate({"score": 1.5}, SCORE_SCHEMA)


def test_score_at_boundaries_accepted(validate):
    validate({"score": 0.0}, SCORE_SCHEMA)
    validate({"score": 1.0}, SCORE_SCHEMA)


# ===================================================================
# SECTION F — Integer type
# ===================================================================


INTEGER_SCHEMA = {
    "type": "object",
    "properties": {"count": {"type": "integer"}},
    "required": ["count"],
}


def test_integer_rejects_float(validate):
    with pytest.raises(ValueError, match="must be integer"):
        validate({"count": 3.5}, INTEGER_SCHEMA)


def test_integer_rejects_bool(validate):
    with pytest.raises(ValueError, match="must be integer"):
        validate({"count": True}, INTEGER_SCHEMA)


def test_integer_accepts_int(validate):
    validate({"count": 3}, INTEGER_SCHEMA)


# ===================================================================
# SECTION G — Other type mismatches
# ===================================================================


def test_string_field_rejects_number(validate):
    data = {"category": 42, "severity": "high", "service": "api"}
    with pytest.raises(ValueError, match="must be string"):
        validate(data, INCIDENT_SCHEMA)


def test_boolean_field_rejects_string(validate):
    data = {
        "category": "net",
        "severity": "high",
        "service": "api",
        "appears_known": "yes",
    }
    with pytest.raises(ValueError, match="must be boolean"):
        validate(data, INCIDENT_SCHEMA)


def test_array_field_rejects_string(validate):
    schema = {
        "type": "object",
        "properties": {"items": {"type": "array"}},
        "required": ["items"],
    }
    with pytest.raises(ValueError, match="must be array"):
        validate({"items": "not-array"}, schema)


# ===================================================================
# SECTION H — Valid outputs pass (regression guard)
# ===================================================================


def test_full_valid_incident_passes(validate):
    data = {
        "category": "network",
        "severity": "high",
        "service": "api",
        "impact_scope": "organization",
        "appears_known": False,
    }
    validate(data, INCIDENT_SCHEMA)


def test_minimal_valid_incident_passes(validate):
    data = {"category": "net", "severity": "high", "service": "api"}
    validate(data, INCIDENT_SCHEMA)


def test_valid_score_passes(validate):
    validate({"score": 0.85, "reason": "Good"}, SCORE_SCHEMA)


# ===================================================================
# SECTION I — Prompt/runtime alignment
# ===================================================================


def test_prompt_does_not_encourage_fabricated_defaults():
    """The AI-op prompt must NOT tell the model to fabricate defaults
    like empty strings or 0 for required fields."""
    runner = AIOperationsRunner.__new__(AIOperationsRunner)
    spec = AI_OPS["ai.assess"]
    schema = INCIDENT_SCHEMA
    prompt = runner._build_system_prompt(spec, "test", schema, {})

    # Must not contain the old dangerous rule
    assert "safest reasonable default" not in prompt.lower()
    assert 'empty string' not in prompt.lower()
    # Should contain the safer policy
    assert "do NOT fabricate" in prompt or "do not fabricate" in prompt.lower()


# ===================================================================
# SECTION J — additionalProperties behavior documentation
# ===================================================================


def test_ai_extract_allows_additional_properties():
    """ai.extract is intentionally schema-flexible: its default schema
    sets additionalProperties: true so it can extract arbitrary fields."""
    schema = AI_OPS["ai.extract"].default_expect_schema
    assert schema.get("additionalProperties") is True


def test_ai_fix_json_allows_additional_properties():
    """ai.fix_json is a repair utility — it must accept arbitrary structure."""
    schema = AI_OPS["ai.fix_json"].default_expect_schema
    assert schema.get("additionalProperties") is True


def test_ai_assess_rejects_additional_properties(validate):
    """ai.assess has explicit properties — extras must be rejected."""
    schema = AI_OPS["ai.assess"].default_expect_schema
    assert "additionalProperties" not in schema
    data = {"result": "ok", "confidence": 0.9, "extra": "bad"}
    with pytest.raises(ValueError, match="Unexpected extra fields"):
        validate(data, schema)


def test_ai_route_rejects_additional_properties(validate):
    """ai.route has explicit properties — extras must be rejected."""
    schema = AI_OPS["ai.route"].default_expect_schema
    data = {"route": "ops", "reason": "test", "extra_field": True}
    with pytest.raises(ValueError, match="Unexpected extra fields"):
        validate(data, schema)


def test_schema_without_type_object_still_enforced(validate):
    """An expect block with properties/required but no "type": "object"
    (an easy YAML omission) must validate like an object schema — the
    prompt promises strict enforcement, so silently no-oping is a hole."""
    schema = {
        "properties": {"result": {"type": "string"}},
        "required": ["result"],
    }
    with pytest.raises(ValueError, match="Missing required field"):
        validate({"other": "x", "wrong": True}, schema)


def test_schema_without_type_object_rejects_extras(validate):
    schema = {
        "properties": {"result": {"type": "string"}},
        "required": ["result"],
    }
    with pytest.raises(ValueError, match="Unexpected extra fields"):
        validate({"result": "ok", "hallucinated": 1}, schema)


def test_schema_without_type_object_accepts_valid(validate):
    schema = {
        "properties": {"result": {"type": "string"}},
        "required": ["result"],
    }
    validate({"result": "ok"}, schema)  # should not raise


def test_schema_without_type_object_rejects_non_dict(validate):
    schema = {"properties": {"result": {"type": "string"}}, "required": ["result"]}
    with pytest.raises(ValueError, match="Expected object"):
        validate(["not", "an", "object"], schema)
