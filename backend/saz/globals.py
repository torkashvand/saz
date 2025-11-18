"""Global singletons for app-level agents and registries."""

from saz.agents.agentic_planner import AgenticPlanner
from saz.agents.critic import CriticAgent
from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.agents.planner_protocol import Planner
from saz.policies.policy_engine import PolicyEngine, create_default_policy_engine
from saz.tools.registry import ToolRegistry, create_default_registry

# Global instances (initialized at app startup)
_TOOL_REGISTRY: ToolRegistry | None = None
_POLICY_ENGINE: PolicyEngine | None = None
_STEP_PLANNER: DeterministicPlanner | None = None  # Deterministic planner
_AGENTIC_PLANNER: AgenticPlanner | None = None  # LLM-based planner
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
        planner_model: LLM model for AgenticPlanner (agentic mode)
        critic_model: LLM model for CriticAgent
    """
    global _TOOL_REGISTRY, _POLICY_ENGINE, _STEP_PLANNER, _AGENTIC_PLANNER, _EXECUTOR, _CRITIC

    # Tool Registry
    _TOOL_REGISTRY = create_default_registry(enable_ai_ops=True)

    # Policy Engine
    _POLICY_ENGINE = policy_engine or create_default_policy_engine()

    # Deterministic Step Planner ($0 planning cost)
    _STEP_PLANNER = DeterministicPlanner()

    # Agentic LLM Planner (for dynamic plan generation)
    _AGENTIC_PLANNER = AgenticPlanner(model=planner_model)

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


def get_step_planner() -> DeterministicPlanner:
    """Get deterministic step planner (must call initialize_globals first)"""
    if _STEP_PLANNER is None:
        raise RuntimeError("Globals not initialized - call initialize_globals() first")
    return _STEP_PLANNER


def get_agentic_planner() -> AgenticPlanner:
    """Get agentic LLM planner (must call initialize_globals first)"""
    if _AGENTIC_PLANNER is None:
        raise RuntimeError("Globals not initialized - call initialize_globals() first")
    return _AGENTIC_PLANNER


def get_planner(mode: str) -> Planner:
    """
    Get appropriate planner based on planning mode.

    Args:
        mode: "deterministic" or "agentic"

    Returns:
        Planner instance (DeterministicPlanner or AgenticPlanner)
    """
    if mode == "deterministic":
        return get_step_planner()
    elif mode == "agentic":
        return get_agentic_planner()
    else:
        raise ValueError(f"Unknown planner mode: {mode}")


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
