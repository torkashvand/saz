"""Pydantic schemas for agent inputs/outputs - ensures structured, validated LLM responses."""

from enum import Enum

from pydantic import BaseModel, Field


class WorkflowStructuralError(ValueError):
    """A permanent workflow/tool/config error that retrying cannot fix.

    Structural errors (unknown tool, unknown step type, missing required
    arguments, unresolved template references, invalid schema) are deterministic
    by definition — retrying with backoff only wastes time and budget. The
    executor's retry loop re-raises these immediately instead of retrying.

    Subclasses ValueError so existing ``except ValueError`` handlers and tests
    that assert ValueError for these conditions keep working unchanged.
    """


class ToolNotFoundError(WorkflowStructuralError):
    """Referenced tool is not registered."""


class InvalidToolArgumentsError(WorkflowStructuralError):
    """Grounded tool arguments are missing/invalid against the tool schema."""


class UnresolvedTemplateError(WorkflowStructuralError):
    """A template reference could not be resolved to a concrete value."""


class UnknownStepTypeError(WorkflowStructuralError):
    """Step type has no executor dispatch."""


class ErrorHandling(str, Enum):
    """How to handle step errors"""

    RETRY = "retry"
    FAIL = "fail"
    ESCALATE = "escalate"
    CONTINUE = "continue"


class PlanStep(BaseModel):
    """Single step in an execution plan"""

    step_id: str = Field(..., description="Unique step identifier matching workflow")
    step_type: str = Field(..., description="Step type from workflow DSL")
    tool_name: str | None = None
    input_template: dict = Field(
        default_factory=dict, description="Tool input with {{variable}} placeholders"
    )
    expected_output_schema: dict = Field(
        default_factory=dict, description="JSON Schema for expected output"
    )
    error_handling: ErrorHandling = ErrorHandling.RETRY
    max_retries: int = 3
    reasoning: str = Field(..., description="Why this step is necessary")


class ExecutionPlan(BaseModel):
    """LLM-generated execution plan for a workflow"""

    plan_id: str = Field(..., pattern=r'^[a-f0-9-]{36}$')
    steps: list[PlanStep]
    estimated_cost_usd: float = Field(..., ge=0)
    estimated_time_seconds: int = Field(..., ge=0)
    reasoning: str = Field(..., description="Overall plan justification")


class ToolCall(BaseModel):
    """Executor's tool invocation request"""

    tool: str
    arguments: dict
    idempotency_key: str
    rationale: str = Field(..., description="Why these specific arguments")


class Verdict(str, Enum):
    """Critic's decision after step execution"""

    PASS = "pass"
    FAIL = "fail"
    REPLAN = "replan"
    ESCALATE = "escalate_to_human"


class Critique(BaseModel):
    """Critic's evaluation of a step execution"""

    verdict: Verdict
    reasoning: str = Field(..., description="Detailed analysis of step result")
    issues: list[str] = Field(default_factory=list, description="Problems found (empty if pass)")
    safety_flags: list[str] = Field(default_factory=list, description="Security/policy concerns")
    suggestions: dict[str, str | None] = Field(default_factory=dict, description="What to do next")
    confidence: float = Field(..., ge=0, le=1, description="Confidence in verdict (0-1)")
