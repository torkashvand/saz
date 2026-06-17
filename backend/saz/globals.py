"""App-level configuration and per-run agent factories.

Only the tool registry is shared across runs: tool specs are immutable and
read-only at execution time. Everything that carries per-run mutable state —
the policy engine (budget caps, rate limits, PII settings, token vaults),
the executor agent (secret resolver), the critic (usage recorder), and the
planners — is constructed fresh per run via the ``create_*`` factories so
concurrent runs cannot contaminate one another's secrets, budgets, or
policy configuration.
"""

from collections.abc import Callable

from saz.agents.agentic_planner import AgenticPlanner
from saz.agents.critic import CriticAgent
from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.agents.planner_protocol import Planner
from saz.domain.literals import PlannerMode
from saz.policies.policy_engine import PolicyEngine, create_default_policy_engine
from saz.settings import settings
from saz.tools.registry import ToolRegistry, create_default_registry

# Shared, read-only singleton. Tool specs are immutable at execution time, so
# the registry is safe to share across concurrent runs.
_TOOL_REGISTRY: ToolRegistry | None = None

# App-level configuration captured at startup. The per-run factories below
# read these to build fresh, isolated instances for each run.
_PLANNER_MODEL: str = "gpt-4o"
_CRITIC_MODEL: str = "gpt-4o"
_POLICY_ENGINE_FACTORY: Callable[[], PolicyEngine] = create_default_policy_engine
_INITIALIZED: bool = False


def initialize_globals(
    policy_engine_factory: Callable[[], PolicyEngine] | None = None,
    planner_model: str = "gpt-4o",
    critic_model: str = "gpt-4o",
) -> None:
    """
    Initialize app-level configuration at startup.

    Args:
        policy_engine_factory: Optional callable that builds a fresh PolicyEngine
            per run. Defaults to ``create_default_policy_engine``. A *factory*
            (not an instance) is required so each run gets isolated state.
        planner_model: LLM model for AgenticPlanner (agentic mode)
        critic_model: LLM model for CriticAgent
    """
    global _TOOL_REGISTRY, _PLANNER_MODEL, _CRITIC_MODEL, _POLICY_ENGINE_FACTORY, _INITIALIZED

    _TOOL_REGISTRY = create_default_registry(
        enable_ai_ops=True,
        artifact_storage_path=settings.ARTIFACT_STORAGE_PATH,
    )
    _PLANNER_MODEL = planner_model
    _CRITIC_MODEL = critic_model
    _POLICY_ENGINE_FACTORY = policy_engine_factory or create_default_policy_engine
    _INITIALIZED = True


def get_tool_registry() -> ToolRegistry:
    """Get the shared, read-only tool registry (call initialize_globals first)."""
    if _TOOL_REGISTRY is None:
        raise RuntimeError("Globals not initialized - call initialize_globals() first")
    return _TOOL_REGISTRY


def create_policy_engine() -> PolicyEngine:
    """Build a fresh policy engine for a single run (no shared mutable state)."""
    return _POLICY_ENGINE_FACTORY()


def create_executor_agent() -> ExecutorAgent:
    """Build a fresh executor/grounding agent for a single run.

    The secret resolver is bound per run by ``WorkflowExecutor`` so credential
    resolution is isolated to that run's unit of work.
    """
    return ExecutorAgent(secret_resolver=None)


def create_critic_agent() -> CriticAgent:
    """Build a fresh critic for a single run.

    Shares the read-only LLM port; the per-run usage recorder is bound by
    ``WorkflowExecutor`` so verifier/critic spend counts against the right run.
    """
    return CriticAgent(model=_CRITIC_MODEL)


def create_planner(mode: PlannerMode | str) -> Planner:
    """Build a fresh planner for the requested mode for a single run."""
    resolved = PlannerMode(mode)
    if resolved is PlannerMode.DETERMINISTIC:
        return DeterministicPlanner()
    return AgenticPlanner(model=_PLANNER_MODEL)
