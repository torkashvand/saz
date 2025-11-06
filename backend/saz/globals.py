"""Global singletons for app-level agents and registries."""

from saz.agents.critic import CriticAgent
from saz.agents.executor import ExecutorAgent
from saz.agents.planner import PlannerAgent
from saz.policies.policy_engine import PolicyEngine, create_default_policy_engine
from saz.tools.registry import ToolRegistry, create_default_registry

# Global instances (initialized at app startup)
_TOOL_REGISTRY: ToolRegistry | None = None
_POLICY_ENGINE: PolicyEngine | None = None
_PLANNER: PlannerAgent | None = None
_EXECUTOR: ExecutorAgent | None = None
_CRITIC: CriticAgent | None = None


def initialize_globals(
    policy_engine: PolicyEngine | None = None,
    planner_model: str = "gpt-4o",
    critic_model: str = "gpt-4o",
) -> None:
    """
    Initialize global singletons at app startup.

    Args:
        policy_engine: Optional custom policy engine (creates default if not provided)
        planner_model: LLM model for PlannerAgent
        critic_model: LLM model for CriticAgent
    """
    global _TOOL_REGISTRY, _POLICY_ENGINE, _PLANNER, _EXECUTOR, _CRITIC

    # Tool Registry
    _TOOL_REGISTRY = create_default_registry(enable_ai_ops=True)

    # Policy Engine
    _POLICY_ENGINE = policy_engine or create_default_policy_engine()

    # Planner Agent
    _PLANNER = PlannerAgent(model=planner_model)

    # Executor Agent (needs secret resolver - will be set per-executor instance)
    _EXECUTOR = ExecutorAgent(secret_resolver=lambda x: None)  # Placeholder

    # Critic Agent
    _CRITIC = CriticAgent(model=critic_model)


def get_tool_registry() -> ToolRegistry:
    """Get global tool registry (must call initialize_globals first)"""
    if _TOOL_REGISTRY is None:
        raise RuntimeError("Globals not initialized - call initialize_globals() first")
    return _TOOL_REGISTRY


def get_policy_engine() -> PolicyEngine:
    """Get global policy engine (must call initialize_globals first)"""
    if _POLICY_ENGINE is None:
        raise RuntimeError("Globals not initialized - call initialize_globals() first")
    return _POLICY_ENGINE


def get_planner() -> PlannerAgent:
    """Get global planner agent (must call initialize_globals first)"""
    if _PLANNER is None:
        raise RuntimeError("Globals not initialized - call initialize_globals() first")
    return _PLANNER


def get_executor() -> ExecutorAgent:
    """Get global executor agent (must call initialize_globals first)"""
    if _EXECUTOR is None:
        raise RuntimeError("Globals not initialized - call initialize_globals() first")
    return _EXECUTOR


def get_critic() -> CriticAgent:
    """Get global critic agent (must call initialize_globals first)"""
    if _CRITIC is None:
        raise RuntimeError("Globals not initialized - call initialize_globals() first")
    return _CRITIC
