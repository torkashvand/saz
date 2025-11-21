"""Error enrichment service for generating user-friendly error summaries."""

from typing import Any

from saz.db.models import Run, Step
from saz.domain.error_categorization import (
    ErrorCategory,
    RemediationAction,
    categorize_error,
    generate_error_message,
    get_remediation_actions,
)


class ErrorSummary:
    """Human-readable error summary with remediation actions."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory,
        failed_step_number: int | None,
        failed_step_name: str | None,
        remediation_actions: list[RemediationAction],
        technical_details: dict[str, Any],
    ):
        self.message = message
        self.category = category
        self.failed_step_number = failed_step_number
        self.failed_step_name = failed_step_name
        self.remediation_actions = remediation_actions
        self.technical_details = technical_details

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "message": self.message,
            "category": self.category.value,
            "failed_step_number": self.failed_step_number,
            "failed_step_name": self.failed_step_name,
            "remediation_actions": [action.value for action in self.remediation_actions],
            "technical_details": self.technical_details,
        }


class ErrorEnrichmentService:
    """Service for enriching errors with user-friendly summaries."""

    @staticmethod
    def build_error_summary(run: Run, failed_step: Step | None = None) -> ErrorSummary | None:
        """
        Build error summary for a failed run.

        Args:
            run: The failed run
            failed_step: The step that failed (if available)

        Returns:
            ErrorSummary or None if no error
        """
        # Determine which error to process
        error_dict = None
        if failed_step and failed_step.error:
            error_dict = failed_step.error
        elif run.error:
            error_dict = run.error

        if not error_dict:
            return None

        # Categorize error
        category = categorize_error(error_dict)

        # Generate human-readable message
        step_name = failed_step.name if failed_step else None
        message = generate_error_message(category, error_dict, step_name)

        # Get remediation actions
        remediation_actions = get_remediation_actions(category)

        # Build technical details (WITHOUT stack traces - those stay in Step.error/Run.error)
        # This ensures stack traces are never sent to frontend by default
        technical_details = {
            "error_type": error_dict.get("type"),
            # DO NOT include stack_trace or traceback here - security concern
            # Frontend can get full details from Step.error if needed
        }

        # Add HTTP-specific details if available
        if "http" in str(error_dict.get("type", "")).lower():
            # Try to extract HTTP status from error message
            error_message = error_dict.get("message", "")
            if "401" in error_message or "403" in error_message:
                technical_details["http_status"] = 401 if "401" in error_message else 403
            elif "500" in error_message:
                technical_details["http_status"] = 500
            elif "404" in error_message:
                technical_details["http_status"] = 404

        return ErrorSummary(
            message=message,
            category=category,
            failed_step_number=failed_step.number if failed_step else None,
            failed_step_name=failed_step.name if failed_step else None,
            remediation_actions=remediation_actions,
            technical_details=technical_details,
        )

    @staticmethod
    def enrich_step_with_failure_reason(step: Step) -> tuple[str | None, str | None]:
        """
        Generate failure reason and error category for a failed step.

        Args:
            step: The step to enrich

        Returns:
            Tuple of (failure_reason, error_category) or (None, None)
        """
        if not step.error or step.status != "failed":
            return None, None

        # Categorize error
        category = categorize_error(step.error)

        # Generate human-readable message
        message = generate_error_message(category, step.error, step.name)

        return message, category.value

    @staticmethod
    def calculate_run_metadata(run: Run) -> dict[str, Any]:
        """
        Calculate aggregated metadata for a run.

        Args:
            run: The run to analyze

        Returns:
            Dictionary with step counts
        """
        steps = run.steps or []

        return {
            "total_steps": len(steps),
            "succeeded_steps": sum(1 for s in steps if s.status in ("completed", "success")),
            "failed_steps": sum(1 for s in steps if s.status == "failed"),
            "running_steps": sum(1 for s in steps if s.status == "running"),
            "skipped_steps": 0,  # Not currently tracked, but reserved for future use
        }

    @staticmethod
    def get_step_description(step: Step, flow_definition: dict | None = None) -> str | None:
        """
        Get user-friendly description for a step from flow definition.

        Args:
            step: The step
            flow_definition: The flow definition (optional)

        Returns:
            Step description or None
        """
        if not flow_definition:
            return None

        # Try to find step definition in workflow
        workflow_steps = flow_definition.get("workflow", {}).get("steps", [])

        for step_def in workflow_steps:
            step_id = step_def.get("id")
            if step_id and step_id == step.name:
                # Try to get description from various fields
                description = step_def.get("description")
                if description:
                    return description

                # Fallback to instruction or action
                instruction = step_def.get("instruction")
                if instruction:
                    return instruction

                # Fallback to action with type
                action = step_def.get("action")
                step_type = step_def.get("type")
                if action and step_type:
                    return f"{step_type.capitalize()}: {action}"

        # Fallback to step type
        if step.step_type:
            return f"{step.step_type.replace('_', ' ').title()} step"

        return None
