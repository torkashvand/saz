"""Run isolation: per-run agents must not share mutable state.

Before the hardening pass the executor agent, critic, and policy engine were
process-wide singletons that ``WorkflowExecutor.__init__`` mutated per run.
Under the scheduler's thread pool (up to EXECUTOR_MAX_WORKERS concurrent runs)
one run could overwrite another run's PII setting, budget caps, rate limits,
or secret resolver.

These tests prove:
  1. The globals factories hand out fresh, independent instances.
  2. Two real runs with divergent PII policy, executed concurrently through
     the real WorkflowExecutor path, do not contaminate each other.
"""

import threading

import pytest
from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.db.models import Flow, Run, Step
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.globals import (
    create_critic_agent,
    create_executor_agent,
    create_planner,
    create_policy_engine,
    initialize_globals,
)
from tests.conftest import TEST_USER_ID
from tests.fakes.critic import FakeCritic
from tests.fakes.tools import RecordingTool

HTTP_SPEC = {
    "name": "http_request",
    "description": "Fake recorded HTTP",
    "inputSchema": {
        "type": "object",
        "properties": {
            "method": {"type": "string"},
            "url": {"type": "string"},
            "body": {"type": "object"},
        },
        "required": ["method", "url"],
    },
}


def _pii_flow_def(name: str, *, allow_body_path: bool, budget_usd: float) -> dict:
    """Outbound PII is blocked unless the path is explicitly allow-listed.
    ``allow_body_path`` controls whether this flow opts ``body.comment`` into
    the per-tool exception list — that allow-list is per-run mutable policy
    state, the exact thing the old singleton leaked across runs."""
    pii: dict = {"allow": False}
    if allow_body_path:
        pii["exceptions"] = {"tools": {"http_request": ["body.comment"]}}
    return {
        "schema_version": 1,
        "flow": {"name": name, "description": "isolation probe"},
        "workflow": {
            "planner_mode": "deterministic",
            "steps": [
                {
                    "id": "leak",
                    "type": "tool.call",
                    "description": "Send a request containing an unmasked email",
                    "tool": "http_request",
                    "params": {
                        "method": "POST",
                        "url": "https://api.example.com/contact",
                        "body": {"comment": "Reach me at user@example.com"},
                    },
                }
            ],
        },
        "policies": {"budget_usd": budget_usd, "pii": pii},
    }


@pytest.fixture(autouse=True)
def _globals_initialized():
    # The factories read app-level config captured here.
    initialize_globals(planner_model="gpt-4o", critic_model="gpt-4o")
    yield


def test_factories_return_isolated_instances():
    """Each factory call returns a distinct object with independent state."""
    pe_a = create_policy_engine()
    pe_b = create_policy_engine()
    assert pe_a is not pe_b
    assert pe_a.budget_tracker is not pe_b.budget_tracker
    assert pe_a.rate_limiter is not pe_b.rate_limiter
    assert pe_a._token_vaults is not pe_b._token_vaults

    # Mutating one engine from DSL must not leak into the other.
    pe_a.initialize_from_dsl("run_a", {"pii": {"allow": True}, "budget_usd": 0.01})
    pe_b.initialize_from_dsl("run_b", {"pii": {"allow": False}, "budget_usd": 99.0})
    assert pe_a.enforce_pii_redaction is False  # allow=True -> not enforced
    assert pe_b.enforce_pii_redaction is True
    assert pe_a.budget_tracker.max_cost_usd == 0.01
    assert pe_b.budget_tracker.max_cost_usd == 99.0

    # Executor agents must not share a secret resolver.
    ex_a = create_executor_agent()
    ex_b = create_executor_agent()
    assert ex_a is not ex_b
    ex_a.secret_resolver = lambda name: "secret-A"
    ex_b.secret_resolver = lambda name: "secret-B"
    assert ex_a.secret_resolver("x") == "secret-A"
    assert ex_b.secret_resolver("x") == "secret-B"

    # Critics and planners are also per-run.
    assert create_critic_agent() is not create_critic_agent()
    assert create_planner("deterministic") is not create_planner("deterministic")


def _seed_flow_and_run(db_engine, flow_id: str, run_id: str, definition: dict) -> None:
    with Session(db_engine) as session:
        session.add_all(
            [
                Flow(
                    created_by_user_id=TEST_USER_ID,
                    id=flow_id,
                    name=flow_id,
                    definition=definition,
                ),
                Run(
                    created_by_user_id=TEST_USER_ID,
                    id=run_id,
                    flow_id=flow_id,
                    status="queued",
                    planner_mode="deterministic",
                    payload={},
                ),
            ]
        )
        session.commit()


def test_concurrent_divergent_pii_policy_does_not_contaminate(db_engine):
    """Run A (pii.allow=false) blocks the outbound call; Run B (pii.allow=true)
    lets it through — even when both execute concurrently and would share a
    policy engine under the old singleton design."""
    _seed_flow_and_run(
        db_engine,
        "flow_iso_a",
        "run_iso_a",
        _pii_flow_def("iso_a", allow_body_path=False, budget_usd=1.0),
    )
    _seed_flow_and_run(
        db_engine,
        "flow_iso_b",
        "run_iso_b",
        _pii_flow_def("iso_b", allow_body_path=True, budget_usd=1.0),
    )

    barrier = threading.Barrier(2)
    results: dict[str, RecordingTool] = {}

    def run_one(run_id: str) -> None:
        # Each run builds its own registry/tool and its own agents via the
        # factories — exactly how the scheduler wires a run.
        tool = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
        registry = create_isolated_registry(tool)
        results[run_id] = tool
        # Maximise interleaving of initialize_from_dsl across the two runs.
        barrier.wait(timeout=5)
        with Session(db_engine) as session:
            with UnitOfWork(session) as uow:
                executor = WorkflowExecutor(
                    uow=uow,
                    tool_registry=registry,
                    planner=DeterministicPlanner(),
                    executor_agent=create_executor_agent(),
                    critic=FakeCritic(),  # type: ignore[arg-type]
                    policy_engine=create_policy_engine(),
                )
                import asyncio

                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(executor.execute_run(run_id))
                except Exception:
                    pass
                finally:
                    loop.close()

    threads = [threading.Thread(target=run_one, args=(rid,)) for rid in ("run_iso_a", "run_iso_b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    # Run A: PII enforced -> outbound tool blocked, run failed.
    assert results["run_iso_a"].call_count == 0, "Run A leaked PII: tool was called"
    # Run B: PII allowed -> outbound tool executed.
    assert results["run_iso_b"].call_count == 1, "Run B was wrongly blocked: PII setting bled in"

    with Session(db_engine) as session:
        run_a = session.get(Run, "run_iso_a")
        run_b = session.get(Run, "run_iso_b")
        assert run_a.status in ("failed", "error")
        assert run_b.status == "completed"
        step_a = session.query(Step).filter(Step.run_id == "run_iso_a").first()
        assert step_a is not None and step_a.status == "failed"


def create_isolated_registry(tool: RecordingTool):
    from saz.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register_custom_tool("http_request", tool.spec, tool.execute)
    return registry
