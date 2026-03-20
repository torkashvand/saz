"""Integration tests for pre-execution blocking behavior.

Proves proposal claim: "planner proposes unsafe action → verifier blocks before
execution → blocked proposal does not cause tool side effects."
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


def _make_plan(steps):
    return ExecutionPlan(
        plan_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
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
        safety_flags=[] if verdict == Verdict.PASS else ["flag"],
        suggestions={},
        confidence=confidence,
    )


def _setup_flow_and_run(session, flow_id, run_id):
    flow = Flow(
        id=flow_id,
        name="test-flow",
        definition={
            "workflow": {
                "planner_mode": "deterministic",
                "steps": [{"id": "s1", "type": "ai.extract", "instruction": "Extract"}],
            },
            "policies": {"budget_usd": 1.0},
        },
    )
    run = Run(
        id=run_id,
        flow_id=flow_id,
        status="pending",
        planner_mode="deterministic",
        payload={"text": "hello"},
    )
    session.add_all([flow, run])
    session.commit()


def _build_executor(uow, planner, critic, tool_execute_mock):
    """Build executor with a trackable tool execution mock."""
    executor_agent = MagicMock(spec=ExecutorAgent)
    executor_agent.ground.return_value = ToolCall(
        tool="ai.extract",
        arguments={"instruction": "Extract data", "data": {"text": "hello"}},
        idempotency_key="test-key",
        rationale="test",
    )

    tool_registry = MagicMock(spec=ToolRegistry)
    tool_registry.get_tool_specs.return_value = []
    tool_registry.get_tool_specs_dict.return_value = {}
    tool_registry.execute_tool = tool_execute_mock

    policy_engine = PolicyEngine()

    return WorkflowExecutor(
        uow=uow,
        tool_registry=tool_registry,
        planner=planner,
        executor_agent=executor_agent,
        critic=critic,
        policy_engine=policy_engine,
    )


def test_verifier_fail_blocks_execution(db_engine):
    """When verifier returns FAIL, tool is never executed."""
    flow_id = "flow-block-fail"
    run_id = "run-block-fail"

    with Session(db_engine) as session:
        _setup_flow_and_run(session, flow_id, run_id)

    plan = _make_plan(
        [
            PlanStep(
                step_id="s1",
                step_type="ai.extract",
                reasoning="Extract data",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            )
        ]
    )

    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    # Pre-execution: FAIL (block)
    critic.verify_proposal = AsyncMock(
        return_value=_make_critique(Verdict.FAIL, "Unsafe tool call")
    )
    # Post-execution critique should never be called
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_execute = AsyncMock(return_value={"result": "ok"})

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            with patch("saz.engine.executor.EventEmitter") as MockEmitter:
                mock_emitter = MagicMock()
                mock_emitter.commit_and_broadcast = AsyncMock()
                MockEmitter.return_value = mock_emitter

                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        # Tool was NEVER called — blocked before execution
        tool_execute.assert_not_called()

        # Verify run is marked as failed
        session2 = TestSession()
        try:
            run = session2.query(Run).filter_by(id=run_id).one()
            assert run.status == "failed"
            assert run.error["type"] == "CritiqueFailure"
        finally:
            session2.close()
    finally:
        session.close()


def test_verifier_escalate_suspends_run(db_engine):
    """When verifier returns ESCALATE, run is suspended without tool execution."""
    flow_id = "flow-block-escalate"
    run_id = "run-block-escalate"

    with Session(db_engine) as session:
        _setup_flow_and_run(session, flow_id, run_id)

    plan = _make_plan(
        [
            PlanStep(
                step_id="s1",
                step_type="ai.extract",
                reasoning="Extract data",
                error_handling=ErrorHandling.ESCALATE,
                max_retries=0,
            )
        ]
    )

    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(
        return_value=_make_critique(Verdict.ESCALATE, "Production data access")
    )
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_execute = AsyncMock(return_value={"result": "ok"})

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            from unittest.mock import patch

            # Create a mock emitter that commits via the real UoW
            def make_committing_emitter(*args, **kwargs):
                mock_emitter = MagicMock()

                async def commit_and_broadcast():
                    uow.commit()

                mock_emitter.commit_and_broadcast = AsyncMock(side_effect=commit_and_broadcast)
                return mock_emitter

            with patch("saz.engine.executor.EventEmitter", side_effect=make_committing_emitter):
                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        # Tool was NEVER called
        tool_execute.assert_not_called()

        # Run is suspended
        session2 = TestSession()
        try:
            run = session2.query(Run).filter_by(id=run_id).one()
            assert run.status == "suspended"
            assert run.error["type"] == "EscalationRequired"
            assert "callback_id" in run.error
        finally:
            session2.close()
    finally:
        session.close()


def test_verifier_pass_allows_execution(db_engine):
    """When verifier returns PASS, tool is executed."""
    flow_id = "flow-allow"
    run_id = "run-allow"

    with Session(db_engine) as session:
        _setup_flow_and_run(session, flow_id, run_id)

    plan = _make_plan(
        [
            PlanStep(
                step_id="s1",
                step_type="ai.extract",
                reasoning="Extract data",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            )
        ]
    )

    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS, "Safe to proceed"))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_execute = AsyncMock(
        return_value={"result": "extracted", "usage": {"tokens": 10, "cost_usd": 0.001}}
    )

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            with patch("saz.engine.executor.EventEmitter") as MockEmitter:
                mock_emitter = MagicMock()
                mock_emitter.commit_and_broadcast = AsyncMock()
                MockEmitter.return_value = mock_emitter

                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        # Tool WAS called
        tool_execute.assert_called_once()

        # Run completed
        session2 = TestSession()
        try:
            run = session2.query(Run).filter_by(id=run_id).one()
            assert run.status == "completed"
        finally:
            session2.close()
    finally:
        session.close()


def test_verifier_replan_exhaustion_fails_run(db_engine):
    """When replans exhausted, run fails without tool execution."""
    flow_id = "flow-replan-exhaust"
    run_id = "run-replan-exhaust"

    with Session(db_engine) as session:
        _setup_flow_and_run(session, flow_id, run_id)

    plan = _make_plan(
        [
            PlanStep(
                step_id="s1",
                step_type="ai.extract",
                reasoning="Extract data",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            )
        ]
    )

    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    # Always returns REPLAN — will exhaust attempts
    critic.verify_proposal = AsyncMock(
        return_value=_make_critique(Verdict.REPLAN, "Needs revision")
    )
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_execute = AsyncMock(return_value={"result": "ok"})

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            with patch("saz.engine.executor.EventEmitter") as MockEmitter:
                mock_emitter = MagicMock()
                mock_emitter.commit_and_broadcast = AsyncMock()
                MockEmitter.return_value = mock_emitter

                executor = _build_executor(uow, planner, critic, tool_execute)
                # In deterministic mode, first REPLAN immediately fails
                asyncio.run(executor.execute_run(run_id))

        # Tool was NEVER called
        tool_execute.assert_not_called()

        # Run failed
        session2 = TestSession()
        try:
            run = session2.query(Run).filter_by(id=run_id).one()
            assert run.status == "failed"
            assert run.error["type"] == "ReplanRequired"
        finally:
            session2.close()
    finally:
        session.close()
