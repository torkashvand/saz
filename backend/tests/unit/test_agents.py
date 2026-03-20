"""Unit tests for agents - AgenticPlanner, ExecutorAgent, CriticAgent."""

import json

import pytest
from pydantic import ValidationError

from saz.agents.agentic_planner import AgenticPlanner
from saz.agents.critic import CriticAgent
from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import (
    Critique,
    ErrorHandling,
    ExecutionPlan,
    PlanStep,
    ToolCall,
    Verdict,
)


@pytest.mark.asyncio
async def test_planner_agent_generates_plan(mock_llm_with_plan):
    """Test AgenticPlanner generates valid execution plan."""
    planner = AgenticPlanner(model="gpt-4o", llm_port=mock_llm_with_plan)

    workflow_spec = {
        "name": "test_workflow",
        "steps": [{"id": "step1", "type": "tool_call", "description": "Test step"}],
    }

    tool_registry = [
        {
            "name": "http_request",
            "description": "Make HTTP request",
            "inputSchema": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        }
    ]

    budget = {
        "remaining_tokens": 10000,
        "max_tokens": 100000,
        "remaining_cost": 5.0,
        "max_cost_usd": 10.0,
        "remaining_steps": 25,
        "max_steps": 50,
    }

    plan = await planner.plan(
        workflow_spec=workflow_spec,
        tool_registry=tool_registry,
        run_id="test-run-123",
        completed_steps=[],
        current_data={"input": "test"},
        budget=budget,
    )

    # Verify plan structure
    assert isinstance(plan, ExecutionPlan)
    assert plan.plan_id == "12345678-1234-1234-1234-123456789abc"
    assert len(plan.steps) == 1
    assert plan.steps[0].step_id == "test_step"
    assert plan.steps[0].tool_name == "http_request"

    # Verify LLM was called with correct parameters
    assert mock_llm_with_plan.call_count == 1
    call = mock_llm_with_plan.calls[0]
    assert call["model"] == "gpt-4o"
    assert call["temperature"] == 0.1
    assert call["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_planner_agent_prompt_formatting(mock_llm_with_plan):
    """Test AgenticPlanner formats prompt with all required fields."""
    planner = AgenticPlanner(llm_port=mock_llm_with_plan)

    workflow_spec = {"name": "test", "steps": []}
    tool_registry = [{"name": "tool1"}]
    budget = {
        "remaining_tokens": 5000,
        "max_tokens": 10000,
        "remaining_cost": 2.5,
        "max_cost_usd": 5.0,
        "remaining_steps": 10,
        "max_steps": 20,
    }

    await planner.plan(
        workflow_spec=workflow_spec,
        tool_registry=tool_registry,
        run_id="run-123",
        completed_steps=["step1"],
        current_data={"key": "value"},
        budget=budget,
    )

    # Check prompt includes all required fields
    call = mock_llm_with_plan.calls[0]
    system_msg = call["messages"][0]["content"]

    assert "run-123" in system_msg
    assert "5000/10000" in system_msg  # Token budget
    assert "$2.5/5.0" in system_msg or "2.5/5.0" in system_msg  # Cost budget
    assert "10/20" in system_msg  # Steps budget
    assert "tool1" in system_msg


@pytest.mark.asyncio
async def test_planner_agent_error_handling(mock_llm_port):
    """Test AgenticPlanner handles LLM errors gracefully."""
    # Mock port that returns invalid JSON
    mock_llm_port.responses = ["invalid json {"]

    planner = AgenticPlanner(llm_port=mock_llm_port)

    with pytest.raises((json.JSONDecodeError, ValueError)):  # Should raise JSON decode error
        await planner.plan(
            workflow_spec={"name": "test", "steps": []},
            tool_registry=[],
            run_id="test",
            completed_steps=[],
            current_data={},
            budget={},
        )


def test_executor_agent_grounds_step():
    """Test ExecutorAgent grounds plan step into tool call."""
    executor = ExecutorAgent()

    step = PlanStep(
        step_id="test_step",
        step_type="tool.call",
        tool_name="http_request",
        input_template={
            "url": "https://api.example.com/users/{{ $form.user_id }}",
            "method": "GET",
        },
        expected_output_schema={},
        reasoning="Fetch user data",
    )

    tool_registry = {
        "http_request": {
            "name": "http_request",
            "inputSchema": {
                "type": "object",
                "properties": {"url": {"type": "string"}, "method": {"type": "string"}},
                "required": ["url", "method"],
            },
        }
    }

    current_data = {
        "form_data": {"user_id": "12345", "other_data": "test"},
        "step_results": {},
    }

    tool_call = executor.ground(
        step=step, tool_registry=tool_registry, current_data=current_data, run_id="run-123"
    )

    # Verify tool call
    assert isinstance(tool_call, ToolCall)
    assert tool_call.tool == "http_request"
    assert tool_call.arguments["url"] == "https://api.example.com/users/12345"
    assert tool_call.arguments["method"] == "GET"
    assert tool_call.idempotency_key == "run-123:test_step"
    assert "Fetch user data" in tool_call.rationale


def test_executor_agent_tool_not_found():
    """Test ExecutorAgent raises error for non-existent tool."""
    executor = ExecutorAgent()

    step = PlanStep(
        step_id="test_step",
        step_type="tool.call",
        tool_name="non_existent_tool",
        input_template={},
        reasoning="Test",
    )

    with pytest.raises(ValueError, match="Tool 'non_existent_tool' not found"):
        executor.ground(step=step, tool_registry={}, current_data={}, run_id="run-123")


def test_executor_agent_missing_required_params():
    """Test ExecutorAgent validates required parameters."""
    executor = ExecutorAgent()

    step = PlanStep(
        step_id="test_step",
        step_type="tool.call",
        tool_name="http_request",
        input_template={"method": "GET"},  # Missing required 'url'
        reasoning="Test",
    )

    tool_registry = {
        "http_request": {"name": "http_request", "inputSchema": {"required": ["url", "method"]}}
    }

    with pytest.raises(ValueError, match="Missing required parameters"):
        executor.ground(step=step, tool_registry=tool_registry, current_data={}, run_id="run-123")


def test_executor_agent_nested_variable_substitution():
    """Test ExecutorAgent handles nested variable paths."""
    executor = ExecutorAgent()

    step = PlanStep(
        step_id="test_step",
        step_type="tool.call",
        tool_name="test_tool",
        input_template={"email": "{{ $form.user.email }}", "city": "{{ $form.user.address.city }}"},
        reasoning="Test nested",
    )

    tool_registry = {"test_tool": {"name": "test_tool", "inputSchema": {"required": []}}}

    current_data = {
        "form_data": {
            "user": {"email": "test@example.com", "address": {"city": "San Francisco"}},
        },
        "step_results": {},
    }

    tool_call = executor.ground(
        step=step, tool_registry=tool_registry, current_data=current_data, run_id="run-123"
    )

    assert tool_call.arguments["email"] == "test@example.com"
    assert tool_call.arguments["city"] == "San Francisco"


@pytest.mark.asyncio
async def test_critic_agent_evaluates_success(mock_llm_with_critique):
    """Test CriticAgent evaluates successful step."""
    critic = CriticAgent(llm_port=mock_llm_with_critique)

    step = PlanStep(
        step_id="test_step",
        step_type="tool.call",
        tool_name="http_request",
        input_template={"url": "https://example.com"},
        expected_output_schema={"type": "object"},
        reasoning="Fetch data",
    )

    tool_call = {"tool": "http_request", "arguments": {"url": "https://example.com"}}

    result = {"status": 200, "data": {"user": "test"}}

    critique = await critic.critique(
        step=step,
        tool_call=tool_call,
        result=result,
        run_id="run-123",
        completed_steps=["previous_step"],
        current_state={"key": "value"},
    )

    # Verify critique structure
    assert isinstance(critique, Critique)
    assert critique.verdict == Verdict.PASS
    assert critique.confidence == 0.95
    assert len(critique.issues) == 0

    # Verify LLM was called
    assert mock_llm_with_critique.call_count == 1


@pytest.mark.asyncio
async def test_critic_agent_prompt_includes_context(mock_llm_with_critique):
    """Test CriticAgent includes all context in prompt."""
    critic = CriticAgent(llm_port=mock_llm_with_critique)

    step = PlanStep(
        step_id="critical_step",
        step_type="tool.call",
        tool_name="test_tool",
        input_template={},
        expected_output_schema={"type": "object", "required": ["result"]},
        reasoning="Critical operation",
    )

    await critic.critique(
        step=step,
        tool_call={"tool": "test_tool"},
        result={"result": "success"},
        run_id="run-456",
        completed_steps=["step1", "step2"],
        current_state={"context": "data"},
    )

    call = mock_llm_with_critique.calls[0]
    system_msg = call["messages"][0]["content"]

    assert "critical_step" in system_msg
    assert "run-456" in system_msg
    assert "step1" in system_msg
    assert "Critical operation" in system_msg


@pytest.mark.asyncio
async def test_critic_agent_error_returns_escalate(mock_llm_port):
    """Test CriticAgent returns ESCALATE verdict on error."""

    # Mock port that raises exception
    async def failing_complete(*args, **kwargs):
        raise Exception("LLM service unavailable")

    mock_llm_port.complete = failing_complete

    critic = CriticAgent(llm_port=mock_llm_port)

    step = PlanStep(
        step_id="test",
        step_type="tool.call",
        tool_name="test",
        input_template={},
        reasoning="test",
    )

    critique = await critic.critique(
        step=step, tool_call={}, result={}, run_id="test", completed_steps=[], current_state={}
    )

    # Should return defensive escalate verdict
    assert critique.verdict == Verdict.ESCALATE
    assert critique.confidence == 0.0
    assert "critic_failure" in critique.safety_flags


def test_plan_step_schema_validation():
    """Test PlanStep Pydantic validation."""
    # Valid plan step
    step = PlanStep(
        step_id="test_step",
        step_type="tool.call",
        tool_name="http_request",
        input_template={"url": "https://example.com"},
        reasoning="Test step",
    )

    assert step.step_id == "test_step"
    assert step.step_type == "tool.call"
    assert step.error_handling == ErrorHandling.RETRY  # Default
    assert step.max_retries == 3  # Default


def test_execution_plan_validation():
    """Test ExecutionPlan Pydantic validation."""
    plan_dict = {
        "plan_id": "12345678-1234-1234-1234-123456789abc",
        "steps": [
            {
                "step_id": "step1",
                "step_type": "tool.call",
                "tool_name": "tool1",
                "reasoning": "Step 1",
            }
        ],
        "estimated_cost_usd": 0.01,
        "estimated_time_seconds": 10,
        "reasoning": "Test plan",
    }

    plan = ExecutionPlan.model_validate(plan_dict)

    assert plan.plan_id == "12345678-1234-1234-1234-123456789abc"
    assert len(plan.steps) == 1
    assert plan.estimated_cost_usd >= 0


def test_critique_validation():
    """Test Critique Pydantic validation."""
    critique_dict = {
        "verdict": "pass",
        "reasoning": "Step completed successfully",
        "issues": [],
        "safety_flags": [],
        "suggestions": {"next": "continue"},
        "confidence": 0.9,
    }

    critique = Critique.model_validate(critique_dict)

    assert critique.verdict == Verdict.PASS
    assert critique.confidence == 0.9
    assert len(critique.issues) == 0


def test_critique_confidence_validation():
    """Test Critique confidence must be 0-1."""
    # Invalid confidence > 1
    with pytest.raises(ValidationError):  # Pydantic validation error
        Critique(
            verdict=Verdict.PASS,
            reasoning="Test",
            confidence=1.5,  # Invalid
        )

    # Invalid confidence < 0
    with pytest.raises(ValidationError):
        Critique(
            verdict=Verdict.PASS,
            reasoning="Test",
            confidence=-0.1,  # Invalid
        )
