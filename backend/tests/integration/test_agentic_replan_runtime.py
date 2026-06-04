"""Integration test for the full agentic replanning loop at runtime.

Proves proposal claim: "verifier requests replan → planner revises the step →
verifier approves the revised proposal → executor runs the revised tool call."

This test exercises execute_run() end-to-end in agentic mode, proving the
replanning loop is real, not just tested in isolation.  Event trail assertions
verify that the audit log records each phase of the replan lifecycle.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.orm import Session, sessionmaker

from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import (
    Critique,
    ErrorHandling,
    ExecutionPlan,
    PlanStep,
    ToolCall,
    Verdict,
)
from saz.db.models import Flow, Run
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.tools.registry import ToolRegistry
from tests.conftest import TEST_USER_ID


def _make_plan(steps, plan_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"):
    return ExecutionPlan(
        plan_id=plan_id,
        steps=steps,
        estimated_cost_usd=0.001,
        estimated_time_seconds=1,
        reasoning="test plan",
    )


def _make_critique(verdict, reasoning="test", confidence=0.9):
    return Critique(
        verdict=verdict,
        reasoning=reasoning,
        issues=[] if verdict == Verdict.PASS else ["issue"],
        safety_flags=[],
        suggestions={"modifications": "use read-only"} if verdict == Verdict.REPLAN else {},
        confidence=confidence,
    )


def _setup_flow_and_run(session, flow_id, run_id, planner_mode="agentic"):
    flow = Flow(
        created_by_user_id=TEST_USER_ID,
        id=flow_id,
        name="test-flow",
        definition={
            "workflow": {
                "planner_mode": planner_mode,
                "steps": [{"id": "s1", "type": "ai.extract", "instruction": "Extract"}],
            },
            "policies": {"budget_usd": 1.0, "max_replan_attempts": 3},
        },
    )
    run = Run(
        created_by_user_id=TEST_USER_ID,
        id=run_id,
        flow_id=flow_id,
        status="queued",
        planner_mode=planner_mode,
        payload={"text": "hello"},
    )
    session.add_all([flow, run])
    session.commit()


def _make_tracking_emitter_factory(uow):
    """Build a factory that creates mock emitters which commit AND record method calls.

    Returns (factory_fn, event_log) where event_log is a shared list of
    (method_name, kwargs) tuples recorded in call order across all emitters
    created by the factory.
    """
    event_log: list[tuple[str, dict]] = []

    # Names of emitter convenience methods whose calls we want to record.
    _tracked_methods = {
        "run_started",
        "run_completed",
        "run_failed",
        "run_suspended",
        "run_resumed",
        "step_started",
        "step_completed",
        "step_failed",
        "tool_started",
        "tool_succeeded",
        "tool_failed",
        "plan_generated",
        "progress_updated",
        "usage_recorded",
        "verifier_approved",
        "verifier_rejected",
        "verifier_replan_requested",
        "verifier_escalated",
        "replan_attempted",
        "replan_succeeded",
        "replan_exhausted",
        "approval_requested",
        "approval_granted",
        "approval_denied",
        "webhook_callback_received",
        "critique_completed",
        "policy_pii_redacted",
    }

    def factory(*args, **kwargs):
        mock_emitter = MagicMock()

        async def commit_and_broadcast():
            uow.commit()

        mock_emitter.commit_and_broadcast = AsyncMock(side_effect=commit_and_broadcast)

        # Wrap each tracked method so it records calls while remaining a no-op otherwise.
        for name in _tracked_methods:

            def make_recorder(method_name):
                def recorder(**kw):
                    event_log.append((method_name, kw))

                return recorder

            setattr(mock_emitter, name, make_recorder(name))

        return mock_emitter

    return factory, event_log


# ---------------------------------------------------------------------------
# Happy path: REPLAN → planner revises → verifier approves → tool executes
# ---------------------------------------------------------------------------


def test_agentic_replan_then_execute(db_engine):
    """Full agentic runtime: REPLAN → planner revises → verifier approves → tool executes.

    Proves the loop is real at the executor level, not just in unit tests.
    Also verifies that the event trail records each replan lifecycle phase.
    """
    flow_id = "flow-agentic-replan"
    run_id = "run-agentic-replan"

    with Session(db_engine) as session:
        _setup_flow_and_run(session, flow_id, run_id, planner_mode="agentic")

    # --- Plans ---
    initial_step = PlanStep(
        step_id="s1",
        step_type="ai.extract",
        reasoning="Extract data",
        error_handling=ErrorHandling.FAIL,
        max_retries=0,
    )
    initial_plan = _make_plan([initial_step])

    revised_step = PlanStep(
        step_id="s1",
        step_type="ai.extract",
        reasoning="Extract data (read-only mode)",
        error_handling=ErrorHandling.FAIL,
        max_retries=0,
    )
    revised_plan = _make_plan([revised_step], plan_id="bbbbbbbb-cccc-dddd-eeee-ffffffffffff")

    planner = MagicMock()
    planner.plan = AsyncMock(side_effect=[initial_plan, revised_plan])

    # --- Executor agent: ground differently per attempt ---
    ground_call_count = 0
    original_tool_call = ToolCall(
        tool="ai.extract",
        arguments={"instruction": "Extract data", "mode": "write"},
        idempotency_key="key-1",
        rationale="original",
    )
    revised_tool_call = ToolCall(
        tool="ai.extract",
        arguments={"instruction": "Extract data", "mode": "read-only"},
        idempotency_key="key-2",
        rationale="revised",
    )

    def ground_side_effect(step, tool_registry, current_data, run_id):
        nonlocal ground_call_count
        ground_call_count += 1
        return original_tool_call if ground_call_count == 1 else revised_tool_call

    executor_agent = MagicMock(spec=ExecutorAgent)
    executor_agent.ground.side_effect = ground_side_effect

    # --- Critic: first REPLAN, then PASS ---
    verify_call_count = 0

    async def verify_side_effect(**kwargs):
        nonlocal verify_call_count
        verify_call_count += 1
        if verify_call_count == 1:
            return _make_critique(Verdict.REPLAN, "Use read-only mode", confidence=0.6)
        return _make_critique(Verdict.PASS, "Revised proposal is safe", confidence=0.95)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(side_effect=verify_side_effect)
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS, "Result OK"))

    # --- Tool registry ---
    tool_registry = MagicMock(spec=ToolRegistry)
    tool_registry.get_tool_specs.return_value = []
    tool_registry.get_tool_specs_dict.return_value = {}
    tool_execute = AsyncMock(
        return_value={"result": "extracted", "usage": {"tokens": 10, "cost_usd": 0.001}},
    )
    tool_registry.execute_tool = tool_execute

    # --- Run ---
    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            factory, event_log = _make_tracking_emitter_factory(uow)

            with patch("saz.engine.executor.EventEmitter", side_effect=factory):
                policy_engine = PolicyEngine()
                executor = WorkflowExecutor(
                    uow=uow,
                    tool_registry=tool_registry,
                    planner=planner,
                    executor_agent=executor_agent,
                    critic=critic,
                    policy_engine=policy_engine,
                )
                asyncio.run(executor.execute_run(run_id))

        # === Prove the full loop happened ===

        # 1. Verifier called twice (REPLAN then PASS)
        assert critic.verify_proposal.call_count == 2

        # 2. Planner called twice (initial + replan revision)
        assert planner.plan.call_count == 2

        # 3. Executor grounded twice (original + revised)
        assert executor_agent.ground.call_count == 2

        # 4. Tool executed once — only the approved revised call
        tool_execute.assert_called_once()
        call_kwargs = tool_execute.call_args
        assert call_kwargs.kwargs.get("arguments", {}).get("mode") == "read-only" or (
            call_kwargs.args and "read-only" in str(call_kwargs)
        )

        # 5. Post-execution critique called
        critic.critique.assert_called_once()

        # 6. Run completed
        session2 = TestSession()
        try:
            run = session2.query(Run).filter_by(id=run_id).one()
            assert run.status == "completed", f"Expected 'completed', got '{run.status}'"
        finally:
            session2.close()

        # === Verify event trail records the replan lifecycle ===
        event_names = [name for name, _ in event_log]

        # Replan request was recorded
        assert "verifier_replan_requested" in event_names
        # Replan attempt was recorded
        assert "replan_attempted" in event_names
        # Replan success was recorded
        assert "replan_succeeded" in event_names
        # Final approval was recorded
        assert "verifier_approved" in event_names
        # Tool execution was recorded
        assert "tool_started" in event_names
        assert "tool_succeeded" in event_names
        # Run lifecycle events present
        assert "run_started" in event_names
        assert "run_completed" in event_names

        # Ordering: replan_requested before verifier_approved
        replan_idx = event_names.index("verifier_replan_requested")
        approved_idx = event_names.index("verifier_approved")
        assert replan_idx < approved_idx, "Replan request must precede final approval"

        # Ordering: verifier_approved before tool_started
        tool_idx = event_names.index("tool_started")
        assert approved_idx < tool_idx, "Approval must precede tool execution"

    finally:
        session.close()


# ---------------------------------------------------------------------------
# Failure path: repeated REPLAN until exhaustion
# ---------------------------------------------------------------------------


def test_agentic_replan_exhaustion_after_multiple_attempts(db_engine):
    """Agentic mode: verifier keeps returning REPLAN until max attempts exhausted.

    Verifies that:
    - Tool is never executed
    - All replan attempts are recorded in the event trail
    - replan_exhausted event is emitted
    - Run fails with ReplanRequired
    """
    flow_id = "flow-agentic-exhaust"
    run_id = "run-agentic-exhaust"

    with Session(db_engine) as session:
        _setup_flow_and_run(session, flow_id, run_id, planner_mode="agentic")

    initial_step = PlanStep(
        step_id="s1",
        step_type="ai.extract",
        reasoning="Extract data",
        error_handling=ErrorHandling.FAIL,
        max_retries=0,
    )
    initial_plan = _make_plan([initial_step])

    replan_step = PlanStep(
        step_id="s1",
        step_type="ai.extract",
        reasoning="Revised extract",
        error_handling=ErrorHandling.FAIL,
        max_retries=0,
    )
    replan_plan = _make_plan([replan_step], plan_id="cccccccc-dddd-eeee-ffff-111111111111")

    planner = MagicMock()
    planner.plan = AsyncMock(side_effect=[initial_plan, replan_plan, replan_plan, replan_plan])

    executor_agent = MagicMock(spec=ExecutorAgent)
    executor_agent.ground.return_value = ToolCall(
        tool="ai.extract",
        arguments={"instruction": "Extract"},
        idempotency_key="key",
        rationale="test",
    )

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(
        return_value=_make_critique(Verdict.REPLAN, "Still not safe"),
    )
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_registry = MagicMock(spec=ToolRegistry)
    tool_registry.get_tool_specs.return_value = []
    tool_registry.get_tool_specs_dict.return_value = {}
    tool_execute = AsyncMock(return_value={"result": "ok"})
    tool_registry.execute_tool = tool_execute

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            factory, event_log = _make_tracking_emitter_factory(uow)

            with patch("saz.engine.executor.EventEmitter", side_effect=factory):
                policy_engine = PolicyEngine()
                executor = WorkflowExecutor(
                    uow=uow,
                    tool_registry=tool_registry,
                    planner=planner,
                    executor_agent=executor_agent,
                    critic=critic,
                    policy_engine=policy_engine,
                )
                asyncio.run(executor.execute_run(run_id))

        # Tool was NEVER executed
        tool_execute.assert_not_called()

        # Verifier called 4 times: original + 3 replans
        assert critic.verify_proposal.call_count == 4

        # Planner called 4 times: initial + 3 replan revisions
        assert planner.plan.call_count == 4

        # Run failed
        session2 = TestSession()
        try:
            run = session2.query(Run).filter_by(id=run_id).one()
            assert run.status == "failed"
            assert run.error["type"] == "ReplanRequired"
            assert "exhausted" in run.error["message"].lower()
        finally:
            session2.close()

        # === Verify event trail ===
        event_names = [name for name, _ in event_log]

        # All 3 replan attempts recorded (attempts 1, 2, 3)
        replan_attempt_events = [e for e in event_log if e[0] == "replan_attempted"]
        assert len(replan_attempt_events) == 3
        # Verify attempt numbers are 1, 2, 3
        attempt_numbers = [e[1].get("attempt") for e in replan_attempt_events]
        assert attempt_numbers == [1, 2, 3]

        # 3 replan_succeeded (planner produced revised plans each time)
        replan_succeeded_events = [e for e in event_log if e[0] == "replan_succeeded"]
        assert len(replan_succeeded_events) == 3

        # replan_exhausted emitted once
        assert event_names.count("replan_exhausted") == 1

        # No verifier_approved (all attempts were REPLAN)
        assert "verifier_approved" not in event_names

        # No tool events (tool never ran)
        assert "tool_started" not in event_names
        assert "tool_succeeded" not in event_names

        # Run lifecycle
        assert "run_started" in event_names
        assert "run_failed" in event_names

    finally:
        session.close()
