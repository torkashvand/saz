"""Planner protocol for workflow planning."""

from typing import Any, Protocol, runtime_checkable

from .schemas import ExecutionPlan


@runtime_checkable
class Planner(Protocol):
    """Protocol for workflow planners."""

    async def plan(
        self,
        workflow_spec: dict[str, Any],
        tool_registry: list[dict[str, Any]],
        run_id: str,
        completed_steps: list[str],
        current_data: dict[str, Any],
        budget: dict[str, Any],
    ) -> ExecutionPlan:
        """
        Generate execution plan.

        Args:
            workflow_spec: Workflow specification
            tool_registry: Available tools
            run_id: Run identifier
            completed_steps: Already completed step IDs
            current_data: Current execution context
            budget: Budget constraints

        Returns:
            ExecutionPlan
        """
        ...
