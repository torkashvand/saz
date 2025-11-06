"""Unit tests for AI operations - first-class AI nodes with schema validation and cost tracking."""

import json

import pytest

from saz.agents.ai_ops import AI_OPS, AIOperationsRunner, AIOpSpec


@pytest.mark.asyncio
async def test_ai_ops_assess_operation(mock_llm_port):
    """Test ai.assess operation for classification/extraction."""
    # Mock LLM returns valid JSON response
    response_json = {"result": "high_risk", "confidence": 0.85}
    mock_llm_port.responses = [json.dumps(response_json)]

    runner = AIOperationsRunner(llm_port=mock_llm_port)

    result = await runner.run_ai_op(
        op_name="ai.assess",
        instruction="Classify the risk level of this transaction",
        data={"amount": 10000, "country": "unknown"},
        expected_schema=None,  # Use default
    )

    # Verify result structure
    assert result["output"]["result"] == "high_risk"
    assert result["output"]["confidence"] == 0.85
    assert result["usage"]["tokens"] == 100
    assert result["usage"]["cost_usd"] > 0
    assert result["metadata"]["op"] == "ai.assess"
    assert result["metadata"]["temperature"] == 0.1  # Low for assess

    # Verify LLM called with correct params
    call = mock_llm_port.calls[0]
    assert call["temperature"] == 0.1
    assert call["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_ai_ops_generate_operation(mock_llm_port):
    """Test ai.generate operation for text generation."""
    mock_llm_port.responses = ["Dear Customer,\n\nThank you for your inquiry."]

    runner = AIOperationsRunner(llm_port=mock_llm_port)

    result = await runner.run_ai_op(
        op_name="ai.generate",
        instruction="Compose a professional email response",
        data={"customer_name": "John", "issue": "refund request"},
    )

    # Verify text output
    assert "Dear Customer" in result["output"]
    assert result["metadata"]["op"] == "ai.generate"
    assert result["metadata"]["temperature"] == 0.4  # Higher for generation

    # Verify no JSON parsing for text mode
    call = mock_llm_port.calls[0]
    assert call["response_format"] is None


@pytest.mark.asyncio
async def test_ai_ops_route_operation(mock_llm_port):
    """Test ai.route operation for decision routing."""
    response_json = {"route": "high_priority", "reason": "Customer is VIP status"}
    mock_llm_port.responses = [json.dumps(response_json)]

    runner = AIOperationsRunner(llm_port=mock_llm_port)

    result = await runner.run_ai_op(
        op_name="ai.route",
        instruction="Route this support ticket",
        data={"ticket": "urgent issue", "customer_tier": "VIP"},
        branches_enum=["high_priority", "normal", "low_priority"],
    )

    # Verify routing decision
    assert result["output"]["route"] == "high_priority"
    assert "VIP" in result["output"]["reason"]

    # Verify prompt includes branches
    call = mock_llm_port.calls[0]
    system_msg = call["messages"][0]["content"]
    assert "high_priority" in system_msg
    assert "normal" in system_msg


@pytest.mark.asyncio
async def test_ai_ops_score_operation(mock_llm_port):
    """Test ai.score operation for numeric scoring."""
    response_json = {"score": 0.75, "reason": "Meets most criteria"}
    mock_llm_port.responses = [json.dumps(response_json)]

    runner = AIOperationsRunner(llm_port=mock_llm_port)

    result = await runner.run_ai_op(
        op_name="ai.score",
        instruction="Score this resume against job requirements",
        data={"resume": "...", "job_desc": "..."},
    )

    # Verify score
    assert result["output"]["score"] == 0.75
    assert 0 <= result["output"]["score"] <= 1  # Validate bounds


@pytest.mark.asyncio
async def test_ai_ops_json_validation(mock_llm_port):
    """Test JSON schema validation for AI ops."""
    # Valid JSON matching schema
    valid_response = {"result": "approved", "confidence": 0.9}
    mock_llm_port.responses = [json.dumps(valid_response)]

    runner = AIOperationsRunner(llm_port=mock_llm_port)

    result = await runner.run_ai_op(op_name="ai.assess", instruction="Test", data={})

    # Should pass validation
    assert result["output"]["result"] == "approved"


@pytest.mark.asyncio
async def test_ai_ops_missing_required_field_fails(mock_llm_port):
    """Test validation fails when required field is missing."""
    # Missing required 'result' field
    invalid_response = {"confidence": 0.9}
    # Return invalid JSON twice (original + repair attempt)
    mock_llm_port.responses = [json.dumps(invalid_response), json.dumps(invalid_response)]

    runner = AIOperationsRunner(llm_port=mock_llm_port)

    with pytest.raises(ValueError):  # Will fail after repair attempt
        await runner.run_ai_op(op_name="ai.assess", instruction="Test", data={})


@pytest.mark.asyncio
async def test_ai_ops_temperature_override(mock_llm_port):
    """Test temperature can be overridden."""
    mock_llm_port.responses = [json.dumps({"result": "test"})]

    runner = AIOperationsRunner(llm_port=mock_llm_port)

    await runner.run_ai_op(
        op_name="ai.assess", instruction="Test", data={}, temperature_override=0.5
    )

    # Verify temperature was overridden
    call = mock_llm_port.calls[0]
    assert call["temperature"] == 0.5


@pytest.mark.asyncio
async def test_ai_ops_max_tokens_override(mock_llm_port):
    """Test max_tokens can be overridden."""
    mock_llm_port.responses = ["Test output"]

    runner = AIOperationsRunner(llm_port=mock_llm_port)

    await runner.run_ai_op(
        op_name="ai.generate", instruction="Test", data={}, max_tokens_override=512
    )

    call = mock_llm_port.calls[0]
    assert call["max_tokens"] == 512


@pytest.mark.asyncio
async def test_ai_ops_cost_calculation(mock_llm_port):
    """Test cost calculation from token usage."""
    mock_llm_port.responses = [json.dumps({"result": "test"})]

    runner = AIOperationsRunner(
        llm_port=mock_llm_port,
        cost_per_1m_tokens=1.0,  # $1 per 1M tokens for easy math
    )

    result = await runner.run_ai_op(op_name="ai.assess", instruction="Test", data={})

    # Mock returns 100 tokens
    expected_cost = (100 / 1_000_000) * 1.0
    assert result["usage"]["cost_usd"] == round(expected_cost, 6)


@pytest.mark.asyncio
async def test_ai_ops_extract_operation(mock_llm_port):
    """Test ai.extract for structured data extraction."""
    response_json = {"name": "John Doe", "email": "john@example.com", "phone": "555-1234"}
    mock_llm_port.responses = [json.dumps(response_json)]

    runner = AIOperationsRunner(llm_port=mock_llm_port)

    result = await runner.run_ai_op(
        op_name="ai.extract",
        instruction="Extract contact information",
        data={"text": "Contact John Doe at john@example.com or 555-1234"},
    )

    # Verify extracted fields
    assert result["output"]["name"] == "John Doe"
    assert result["output"]["email"] == "john@example.com"
    assert result["output"]["phone"] == "555-1234"


@pytest.mark.asyncio
async def test_ai_ops_with_word_cap_constraint(mock_llm_port):
    """Test AI ops with word_cap constraint in prompt."""
    mock_llm_port.responses = ["Short summary here."]

    runner = AIOperationsRunner(llm_port=mock_llm_port)

    await runner.run_ai_op(
        op_name="ai.summarize",
        instruction="Summarize this document",
        data={"document": "Long text..."},
        word_cap=50,
    )

    # Verify word_cap in prompt
    call = mock_llm_port.calls[0]
    system_msg = call["messages"][0]["content"]
    assert "50 words" in system_msg or "50" in system_msg


@pytest.mark.asyncio
async def test_ai_ops_with_tools_allowlist(mock_llm_port):
    """Test ai.plan with tools_allowlist constraint."""
    response_json = {
        "calls": [{"tool": "http_request", "args": {"url": "https://api.example.com"}}]
    }
    mock_llm_port.responses = [json.dumps(response_json)]

    runner = AIOperationsRunner(llm_port=mock_llm_port)

    await runner.run_ai_op(
        op_name="ai.plan",
        instruction="Plan the next steps",
        data={},
        tools_allowlist=["http_request", "artifact_store"],
    )

    # Verify allowlist in prompt
    call = mock_llm_port.calls[0]
    system_msg = call["messages"][0]["content"]
    assert "http_request" in system_msg
    assert "artifact_store" in system_msg


@pytest.mark.asyncio
async def test_ai_ops_unknown_operation_fails(mock_llm_port):
    """Test unknown AI operation raises ValueError."""
    runner = AIOperationsRunner(llm_port=mock_llm_port)

    with pytest.raises(ValueError, match="Unknown AI operation"):
        await runner.run_ai_op(op_name="ai.nonexistent", instruction="Test", data={})


@pytest.mark.asyncio
async def test_ai_ops_type_validation(mock_llm_port):
    """Test type validation for JSON fields."""
    # Invalid type: score should be number, not string
    invalid_response = {
        "score": "high",  # Should be 0-1 float
        "reason": "Test",
    }
    # Return invalid JSON twice (original + repair attempt)
    mock_llm_port.responses = [json.dumps(invalid_response), json.dumps(invalid_response)]

    runner = AIOperationsRunner(llm_port=mock_llm_port)

    with pytest.raises(ValueError):  # Will fail after repair attempt
        await runner.run_ai_op(op_name="ai.score", instruction="Test", data={})


@pytest.mark.asyncio
async def test_ai_ops_bounds_validation(mock_llm_port):
    """Test numeric bounds validation."""
    # Score out of bounds
    invalid_response = {
        "score": 1.5,  # Max is 1.0
        "reason": "Test",
    }
    # Return invalid JSON twice (original + repair attempt)
    mock_llm_port.responses = [json.dumps(invalid_response), json.dumps(invalid_response)]

    runner = AIOperationsRunner(llm_port=mock_llm_port)

    with pytest.raises(ValueError):  # Will fail after repair attempt
        await runner.run_ai_op(op_name="ai.score", instruction="Test", data={})


def test_ai_ops_registry_completeness():
    """Test AI_OPS registry contains all expected operations."""
    expected_ops = [
        "ai.assess",
        "ai.generate",
        "ai.plan",
        "ai.extract",
        "ai.route",
        "ai.score",
        "ai.normalize",
        "ai.match",
        "ai.evaluate",
        "ai.compare",
        "ai.translate",
        "ai.summarize",
        "ai.fix_json",
    ]

    for op in expected_ops:
        assert op in AI_OPS, f"Missing AI operation: {op}"

    # Verify each has required fields
    for op_name, spec in AI_OPS.items():
        assert isinstance(spec, AIOpSpec)
        assert spec.name == op_name
        assert spec.temperature >= 0 and spec.temperature <= 2
        assert spec.output_format in ["json", "text"]


def test_ai_op_spec_defaults():
    """Test AIOpSpec has sensible defaults."""
    spec = AI_OPS["ai.assess"]

    assert spec.temperature == 0.1  # Low for deterministic
    assert spec.output_format == "json"
    assert spec.max_tokens > 0
    assert spec.default_expect_schema is not None


def test_ai_ops_temperature_ranges():
    """Test temperature values are within valid ranges."""
    for op_name, spec in AI_OPS.items():
        assert 0 <= spec.temperature <= 2, f"{op_name} has invalid temperature"

    # Verify deterministic ops have low temperature
    deterministic_ops = ["ai.assess", "ai.extract", "ai.route", "ai.score"]
    for op_name in deterministic_ops:
        assert AI_OPS[op_name].temperature <= 0.2, f"{op_name} should be deterministic"


@pytest.mark.asyncio
async def test_ai_ops_metadata_returned(mock_llm_port):
    """Test AI ops returns complete metadata."""
    mock_llm_port.responses = [json.dumps({"result": "test"})]

    runner = AIOperationsRunner(default_model="gpt-4o-mini", llm_port=mock_llm_port)

    result = await runner.run_ai_op(op_name="ai.assess", instruction="Test", data={})

    # Verify complete metadata
    assert "output" in result
    assert "usage" in result
    assert "metadata" in result

    assert "tokens" in result["usage"]
    assert "cost_usd" in result["usage"]

    assert result["metadata"]["op"] == "ai.assess"
    assert "temperature" in result["metadata"]
    assert "model" in result["metadata"]
    assert "max_tokens" in result["metadata"]
