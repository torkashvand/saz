"""Pydantic schemas for agent inputs/outputs - ensures structured, validated LLM responses."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


# Step types the executor can dispatch (see WorkflowExecutor._execute_step_action).
# ``ai.*`` and ``artifact.*`` are open prefixes; the rest are exact.
_EXACT_STEP_TYPES = frozenset({"tool.call", "condition", "human.approval", "webhook.wait"})


def _is_known_step_type(step_type: str) -> bool:
    return (
        step_type in _EXACT_STEP_TYPES
        or step_type.startswith("ai.")
        or step_type.startswith("artifact.")
    )


class PlanStep(BaseModel):
    """Single step in an execution plan.

    ``extra="forbid"`` rejects hallucinated fields from an LLM planner so a
    plan with unexpected keys fails validation instead of being silently
    accepted.
    """

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(..., description="Unique step identifier matching workflow")
    step_type: str = Field(..., description="Step type from workflow DSL")
    tool_name: str | None = None
    guard: str | None = Field(
        default=None,
        description="Optional boolean expression (DSL `when`); the step is "
        "skipped without side effects when it evaluates false.",
    )
    input_template: dict = Field(
        default_factory=dict, description="Tool input with {{variable}} placeholders"
    )
    expected_output_schema: dict = Field(
        default_factory=dict, description="JSON Schema for expected output"
    )
    error_handling: ErrorHandling = ErrorHandling.RETRY
    max_retries: int = 3
    reasoning: str = Field(..., description="Why this step is necessary")

    @model_validator(mode="after")
    def _validate_step_type_and_tool(self) -> "PlanStep":
        if not _is_known_step_type(self.step_type):
            raise ValueError(
                f"Unknown step_type {self.step_type!r}. Expected one of "
                f"{sorted(_EXACT_STEP_TYPES)} or an ai.*/artifact.* type."
            )
        # A tool.call step must name the tool it invokes; otherwise grounding
        # has nothing to execute. ai.*/artifact.* derive the tool from the
        # type, and control steps (condition/human.approval/webhook.wait) need
        # no tool.
        if self.step_type == "tool.call" and not self.tool_name:
            raise ValueError("tool.call step requires a non-empty tool_name")
        return self


class ExecutionPlan(BaseModel):
    """LLM-generated execution plan for a workflow.

    ``extra="forbid"`` rejects hallucinated top-level fields from an LLM
    planner instead of silently accepting them.
    """

    model_config = ConfigDict(extra="forbid")

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
    """Critic's evaluation of a step execution.

    ``extra="forbid"`` mirrors ExecutionPlan/PlanStep: the critic prompts say
    "Return ONLY this JSON structure", so hallucinated fields fail validation
    and route through the critic's fail-safe ESCALATE path instead of being
    silently dropped.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    reasoning: str = Field(..., description="Detailed analysis of step result")
    issues: list[str] = Field(default_factory=list, description="Problems found (empty if pass)")
    safety_flags: list[str] = Field(default_factory=list, description="Security/policy concerns")
    suggestions: dict[str, str | None] = Field(default_factory=dict, description="What to do next")
    confidence: float = Field(..., ge=0, le=1, description="Confidence in verdict (0-1)")
