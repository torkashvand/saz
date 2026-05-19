"""Compiler-allowed step types must match what the executor can actually run.

Two confirmed drift cases:
  1. The compiler's _ALLOWED_STEP_TYPES includes group.parallel, group.map,
     and noop, but engine/executor.py:_execute_step_action only knows
     ai.*/tool.call/artifact.*/condition/human.approval/webhook.wait —
     anything else raises "Unknown step_type" at runtime. A flow can pass
     compile-time validation today and crash on first execution.
  2. ai.plan is exposed by AI_OPS (ai_ops.py:75) and policy MODEL_TOOLS
     (policy_engine.py:18), but the compiler's _ALLOWED_STEP_TYPES omits
     it — so the documented/registered AI op can never be declared in a
     DSL workflow.

This test does not prescribe which side wins (compiler vs runtime). It just
asserts the two layers agree on what's supported.
"""

from saz.agents.ai_ops import AI_OPS
from saz.compiler.dsl import _ALLOWED_STEP_TYPES
from saz.policies.policy_engine import MODEL_TOOLS

# Step types the engine/executor.py:_execute_step_action() understands.
# Source-of-truth: the if/elif chain that dispatches step_type:
#   if t.startswith("ai.") or t == "tool.call" or t.startswith("artifact."):
#   elif t == "condition":
#   elif t == "human.approval":
#   elif t == "webhook.wait":
#   else: raise ValueError(f"Unknown step_type: {t!r} ...")
_RUNTIME_SUPPORTED_CONCRETE: set[str] = {
    "tool.call",
    "condition",
    "human.approval",
    "webhook.wait",
    "artifact.store",
    "artifact.retrieve",
}


def _is_runtime_supported(step_type: str) -> bool:
    if step_type in _RUNTIME_SUPPORTED_CONCRETE:
        return True
    if step_type.startswith("ai."):
        # ai.* is routed to _execute_tool_call → ToolRegistry. It only really
        # works for AI ops registered with the registry.
        return step_type in AI_OPS
    if step_type.startswith("artifact."):
        return True
    return False


def test_every_compiler_allowed_step_type_is_runnable():
    """Compiler should not let a flow through that the executor can't run."""
    unrunnable = sorted(t for t in _ALLOWED_STEP_TYPES if not _is_runtime_supported(t))
    assert unrunnable == [], (
        "Compiler allows step types the runtime cannot execute: "
        f"{unrunnable}. _execute_step_action() will raise 'Unknown step_type' "
        "for these. Either implement them in the executor or remove them "
        "from _ALLOWED_STEP_TYPES."
    )


def test_ai_plan_is_consistent_across_compiler_registry_and_policy():
    """ai.plan must be declared in all three layers or none."""
    in_ai_ops = "ai.plan" in AI_OPS
    in_compiler = "ai.plan" in _ALLOWED_STEP_TYPES
    in_policy_model_tools = "ai.plan" in MODEL_TOOLS

    states = {
        "AI_OPS": in_ai_ops,
        "compiler._ALLOWED_STEP_TYPES": in_compiler,
        "policy MODEL_TOOLS": in_policy_model_tools,
    }
    assert in_ai_ops == in_compiler == in_policy_model_tools, (
        "ai.plan support disagrees across layers: "
        f"{states}. Today AI_OPS and MODEL_TOOLS declare ai.plan but the "
        "compiler does not — so an ai.plan step cannot be authored in a DSL "
        "workflow even though the runtime recognizes the operation."
    )
