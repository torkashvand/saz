"""Tests for DeterministicPlanner (deterministic YAML→Plan converter)."""

import pytest

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.schemas import ErrorHandling, StepAction


@pytest.fixture
def planner():
    """Create a DeterministicPlanner instance."""
    return DeterministicPlanner()


@pytest.fixture
def sample_workflow_spec():
    """Sample workflow spec with mixed step types."""
    return {
        "name": "test_workflow",
        "steps": [
            {
                "id": "plan_step",
                "type": "ai.generate",
                "instruction": "Generate deployment plan",
                "params": {"data": {"request": "deploy app"}},
                "schema": {"type": "object", "properties": {"mode": {"type": "string"}}},
                "temperature": 0.1,
            },
            {
                "id": "execute_step",
                "type": "tool.call",
                "tool": "ansible_run",
                "description": "Execute the planned deployment",
                "params": {"mode": "{{ $step('plan_step').mode }}"},
                "retry": {"attempts": 2},
            },
            {
                "id": "verify_step",
                "type": "condition",
                "description": "Verify deployment succeeded",
                "if": "{{ $step('execute_step').status }} == 'success'",
            },
        ],
    }


class TestStepPlanner:
    """Test suite for DeterministicPlanner."""

    @pytest.mark.asyncio
    async def test_plan_converts_steps_deterministically(self, planner, sample_workflow_spec):
        """Test that planner converts YAML steps 1:1 to PlanSteps."""
        plan = await planner.plan(
            workflow_spec=sample_workflow_spec,
            tool_registry=[],
            run_id="test_run",
            completed_steps=[],
            current_data={},
            budget={},
        )

        assert len(plan.steps) == 3
        assert plan.steps[0].step_id == "plan_step"
        assert plan.steps[1].step_id == "execute_step"
        assert plan.steps[2].step_id == "verify_step"

        # Verify no planning cost (deterministic)
        assert plan.estimated_cost_usd == 0.0
        assert "Deterministic" in plan.reasoning

    @pytest.mark.asyncio
    async def test_ai_step_conversion(self, planner):
        """Test conversion of ai.generate step."""
        workflow_spec = {
            "name": "test",
            "steps": [
                {
                    "id": "ai_step",
                    "type": "ai.generate",
                    "instruction": "Generate something",
                    "params": {"data": {"input": "test"}},
                    "schema": {"type": "object"},
                    "temperature": 0.5,
                    "max_tokens": 1024,
                }
            ],
        }

        plan = await planner.plan(
            workflow_spec=workflow_spec,
            tool_registry=[],
            run_id="test_run",
            completed_steps=[],
            current_data={},
            budget={},
        )

        step = plan.steps[0]
        assert step.step_id == "ai_step"
        assert step.action == StepAction.TOOL_CALL  # AI ops are MCP tools
        assert step.tool_name == "ai.generate"
        assert step.input_template["instruction"] == "Generate something"
        assert step.input_template["data"] == {"input": "test"}
        assert step.input_template["expected_schema"] == {"type": "object"}
        assert step.input_template["temperature_override"] == 0.5
        assert step.input_template["max_tokens_override"] == 1024

    @pytest.mark.asyncio
    async def test_tool_call_conversion(self, planner):
        """Test conversion of tool.call step."""
        workflow_spec = {
            "name": "test",
            "steps": [
                {
                    "id": "tool_step",
                    "type": "tool.call",
                    "tool": "http_request",
                    "description": "Make HTTP request",
                    "params": {"url": "https://api.example.com", "method": "GET"},
                    "retry": {"attempts": 3},
                }
            ],
        }

        plan = await planner.plan(
            workflow_spec=workflow_spec,
            tool_registry=[],
            run_id="test_run",
            completed_steps=[],
            current_data={},
            budget={},
        )

        step = plan.steps[0]
        assert step.step_id == "tool_step"
        assert step.action == StepAction.TOOL_CALL
        assert step.tool_name == "http_request"
        assert step.input_template == {"url": "https://api.example.com", "method": "GET"}
        assert step.max_retries == 3
        assert step.error_handling == ErrorHandling.RETRY

    @pytest.mark.asyncio
    async def test_condition_conversion(self, planner):
        """Test conversion of condition step."""
        workflow_spec = {
            "name": "test",
            "steps": [
                {
                    "id": "check",
                    "type": "condition",
                    "description": "Check if approved",
                    "if": "{{ $form.approved }} == true",
                }
            ],
        }

        plan = await planner.plan(
            workflow_spec=workflow_spec,
            tool_registry=[],
            run_id="test_run",
            completed_steps=[],
            current_data={},
            budget={},
        )

        step = plan.steps[0]
        assert step.step_id == "check"
        assert step.action == StepAction.CONDITION
        assert step.input_template["condition"] == "{{ $form.approved }} == true"

    @pytest.mark.asyncio
    async def test_human_approval_conversion(self, planner):
        """Test conversion of human.approval step."""
        workflow_spec = {
            "name": "test",
            "steps": [
                {
                    "id": "approve",
                    "type": "human.approval",
                    "description": "Approve the deployment",
                    "params": {"approval_required_from": "ops_team"},
                }
            ],
        }

        plan = await planner.plan(
            workflow_spec=workflow_spec,
            tool_registry=[],
            run_id="test_run",
            completed_steps=[],
            current_data={},
            budget={},
        )

        step = plan.steps[0]
        assert step.step_id == "approve"
        assert step.action == StepAction.HUMAN_APPROVAL
        assert step.error_handling == ErrorHandling.ESCALATE  # Default for approval

    @pytest.mark.asyncio
    async def test_artifact_store_conversion(self, planner):
        """Test conversion of artifact.store step."""
        workflow_spec = {
            "name": "test",
            "steps": [
                {
                    "id": "store",
                    "type": "artifact.store",
                    "description": "Store results",
                    "params": {"name": "results", "content": {"data": "value"}},
                }
            ],
        }

        plan = await planner.plan(
            workflow_spec=workflow_spec,
            tool_registry=[],
            run_id="test_run",
            completed_steps=[],
            current_data={},
            budget={},
        )

        step = plan.steps[0]
        assert step.step_id == "store"
        assert step.tool_name == "artifact.store"
        assert step.input_template == {"name": "results", "content": {"data": "value"}}

    @pytest.mark.asyncio
    async def test_filters_completed_steps(self, planner, sample_workflow_spec):
        """Test that completed steps are filtered out."""
        plan = await planner.plan(
            workflow_spec=sample_workflow_spec,
            tool_registry=[],
            run_id="test_run",
            completed_steps=["plan_step"],  # This step already completed
            current_data={},
            budget={},
        )

        # Should only have 2 remaining steps
        assert len(plan.steps) == 2
        assert plan.steps[0].step_id == "execute_step"
        assert plan.steps[1].step_id == "verify_step"

    @pytest.mark.asyncio
    async def test_error_handling_defaults(self, planner):
        """Test default error handling strategies by step type."""
        workflow_spec = {
            "name": "test",
            "steps": [
                {"id": "ai_step", "type": "ai.extract", "instruction": "Extract data"},
                {
                    "id": "tool_step",
                    "type": "tool.call",
                    "tool": "http_request",
                    "description": "Call API",
                    "params": {},
                },
                {"id": "approval", "type": "human.approval", "description": "Approve"},
                {"id": "check", "type": "condition", "description": "Check", "if": "true"},
            ],
        }

        plan = await planner.plan(
            workflow_spec=workflow_spec,
            tool_registry=[],
            run_id="test_run",
            completed_steps=[],
            current_data={},
            budget={},
        )

        # AI steps: retry by default
        assert plan.steps[0].error_handling == ErrorHandling.RETRY

        # Tool steps: retry by default
        assert plan.steps[1].error_handling == ErrorHandling.RETRY

        # Human approval: escalate by default
        assert plan.steps[2].error_handling == ErrorHandling.ESCALATE

        # Condition: fail by default
        assert plan.steps[3].error_handling == ErrorHandling.FAIL

    @pytest.mark.asyncio
    async def test_respects_explicit_retry_config(self, planner):
        """Test that explicit retry configuration overrides defaults."""
        workflow_spec = {
            "name": "test",
            "steps": [
                {
                    "id": "tool_step",
                    "type": "tool.call",
                    "tool": "http_request",
                    "description": "Call API",
                    "params": {},
                    "retry": {"attempts": 5},
                }
            ],
        }

        plan = await planner.plan(
            workflow_spec=workflow_spec,
            tool_registry=[],
            run_id="test_run",
            completed_steps=[],
            current_data={},
            budget={},
        )

        step = plan.steps[0]
        assert step.max_retries == 5
        assert step.error_handling == ErrorHandling.RETRY
