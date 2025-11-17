"""Tests for PlannerAgent (agentic mode LLM planner)."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from saz.agents.planner import PlannerAgent
from saz.agents.schemas import ExecutionPlan


@pytest.fixture
def planner():
    """Create a PlannerAgent instance with mocked LLM port."""
    mock_llm_port = Mock()
    return PlannerAgent(model="gpt-4o", llm_port=mock_llm_port)


@pytest.fixture
def mock_llm_response():
    """Mock LLM response with valid ExecutionPlan JSON."""
    return Mock(
        content='{"plan_id": "550e8400-e29b-41d4-a716-446655440000", '
        '"steps": [{"step_id": "analyze", "action": "tool_call", "tool_name": "ai.extract", '
        '"input_template": {"instruction": "Extract incident details", '
        '"data": {"text": "{{ $form.incident_summary }}"}},'
        ' "expected_output_schema": {"type": "object"}, '
        '"error_handling": "retry", "max_retries": 2, '
        '"reasoning": "Extract structured data from incident"}],'
        ' "estimated_cost_usd": 0.02, "estimated_time_seconds": 5, '
        '"reasoning": "Plan to analyze and route incident"}',
        total_tokens=500,
    )


@pytest.fixture
def sample_agentic_workflow():
    """Sample agentic workflow spec with empty steps."""
    return {
        "name": "incident_triage",
        "planner_mode": "agentic",
        "steps": [],  # Empty - LLM generates
    }


@pytest.fixture
def sample_tool_registry():
    """Sample tool registry."""
    return [
        {
            "name": "ai.extract",
            "description": "Extract structured data",
            "input_schema": {"type": "object"},
        },
        {
            "name": "http_request",
            "description": "Make HTTP request",
            "input_schema": {"type": "object"},
        },
    ]


class TestPlannerAgent:
    """Test suite for PlannerAgent (agentic LLM planner)."""

    @pytest.mark.asyncio
    async def test_plan_with_empty_steps(
        self, planner, sample_agentic_workflow, sample_tool_registry, mock_llm_response
    ):
        """Test agentic planning with empty workflow.steps."""
        with patch.object(
            planner.llm_port, 'complete', new=AsyncMock(return_value=mock_llm_response)
        ):
            plan = await planner.plan(
                workflow_spec=sample_agentic_workflow,
                tool_registry=sample_tool_registry,
                run_id="test_run",
                completed_steps=[],
                current_data={"incident": "test"},
                budget={
                    "remaining_tokens": 10000,
                    "max_tokens": 100000,
                    "remaining_cost": 1.0,
                    "max_cost_usd": 2.0,
                    "remaining_steps": 10,
                    "max_steps": 20,
                },
            )

            assert isinstance(plan, ExecutionPlan)
            assert plan.plan_id == "550e8400-e29b-41d4-a716-446655440000"
            assert len(plan.steps) == 1
            assert plan.steps[0].step_id == "analyze"
            assert plan.steps[0].tool_name == "ai.extract"

    @pytest.mark.asyncio
    async def test_prompt_formatting_works(
        self, planner, sample_agentic_workflow, sample_tool_registry, mock_llm_response
    ):
        """Test that prompt formatting doesn't raise KeyError."""
        with patch.object(
            planner.llm_port, 'complete', new=AsyncMock(return_value=mock_llm_response)
        ) as mock_complete:
            await planner.plan(
                workflow_spec=sample_agentic_workflow,
                tool_registry=sample_tool_registry,
                run_id="test_run",
                completed_steps=[],
                current_data={},
                budget={
                    "remaining_tokens": 10000,
                    "max_tokens": 100000,
                    "remaining_cost": 1.0,
                    "max_cost_usd": 2.0,
                    "remaining_steps": 10,
                    "max_steps": 20,
                },
            )

            # Verify LLM was called
            assert mock_complete.called
            call_args = mock_complete.call_args
            messages = call_args.kwargs["messages"]

            # Verify prompt was formatted successfully (no KeyError)
            assert len(messages) == 2
            assert messages[0]["role"] == "system"
            assert "agentic workflow planner" in messages[0]["content"]
            assert "test_run" in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_plan_with_hint_steps(self, planner, sample_tool_registry, mock_llm_response):
        """Test agentic planning with workflow.steps as hints."""
        workflow_with_hints = {
            "name": "guided_flow",
            "planner_mode": "agentic",
            "steps": [
                {"id": "hint1", "type": "ai.extract", "instruction": "Extract data"},
                {
                    "id": "hint2",
                    "type": "tool.call",
                    "tool": "http_request",
                    "description": "Call API",
                },
            ],
        }

        with patch.object(
            planner.llm_port, 'complete', new=AsyncMock(return_value=mock_llm_response)
        ):
            plan = await planner.plan(
                workflow_spec=workflow_with_hints,
                tool_registry=sample_tool_registry,
                run_id="test_run",
                completed_steps=[],
                current_data={},
                budget={
                    "remaining_tokens": 10000,
                    "max_tokens": 100000,
                    "remaining_cost": 1.0,
                    "max_cost_usd": 2.0,
                    "remaining_steps": 10,
                    "max_steps": 20,
                },
            )

            # Should still generate a plan (LLM may adapt hints)
            assert isinstance(plan, ExecutionPlan)

    @pytest.mark.asyncio
    async def test_planning_failure_handling(
        self, planner, sample_agentic_workflow, sample_tool_registry
    ):
        """Test that planning failures are logged and re-raised."""
        with patch.object(
            planner.llm_port, 'complete', new=AsyncMock(side_effect=Exception("LLM timeout"))
        ):
            with pytest.raises(Exception, match="LLM timeout"):
                await planner.plan(
                    workflow_spec=sample_agentic_workflow,
                    tool_registry=sample_tool_registry,
                    run_id="test_run",
                    completed_steps=[],
                    current_data={},
                    budget={},
                )
