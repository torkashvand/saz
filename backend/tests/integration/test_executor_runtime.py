"""Integration tests for executor runtime behavior.

These tests exercise the real executor.execute_run() path with a real database,
verifying that PII policy derivation and ReplanRequired handling work correctly
at the runtime level (not just in isolated helpers).
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


def _make_plan(steps: list[PlanStep]) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        steps=steps,
        estimated_cost_usd=0.001,
        estimated_time_seconds=1,
        reasoning="test plan",
    )


def _make_critique(verdict: Verdict = Verdict.PASS) -> Critique:
    return Critique(
        verdict=verdict,
        reasoning="test",
        issues=[],
        safety_flags=[],
        suggestions={},
        confidence=0.9,
    )


def _setup_flow_and_run(session, flow_id, run_id, pii_allow=False):
    """Insert a flow and run into the DB."""
    flow = Flow(
        created_by_user_id=TEST_USER_ID,
        id=flow_id,
        name="test-flow",
        definition={
            "workflow": {
                "planner_mode": "deterministic",
                "steps": [
                    {
                        "id": "s1",
                        "type": "ai.extract",
                        "instruction": "Extract data",
                    }
                ],
            },
            "policies": {
                "budget_usd": 1.0,
                "pii": {"allow": pii_allow},
            },
        },
    )
    run = Run(
        created_by_user_id=TEST_USER_ID,
        id=run_id,
        flow_id=flow_id,
        status="pending",
        planner_mode="deterministic",
        payload={"text": "hello"},
    )
    session.add_all([flow, run])
    session.commit()


def _make_pass_verification():
    """Create a Critique with PASS verdict for pre-execution verification."""
    return Critique(
        verdict=Verdict.PASS,
        reasoning="Proposal verified safe",
        issues=[],
        safety_flags=[],
        suggestions={},
        confidence=0.95,
    )


def _build_executor(uow, planner, critic, tool_result=None):
    """Build a WorkflowExecutor with mocked agents."""
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
    tool_registry.execute_tool = AsyncMock(
        return_value=tool_result or {"result": "ok", "usage": {"tokens": 10, "cost_usd": 0.001}}
    )

    # Ensure verify_proposal is an AsyncMock (pre-execution verification)
    if not hasattr(critic, 'verify_proposal') or not isinstance(critic.verify_proposal, AsyncMock):
        critic.verify_proposal = AsyncMock(return_value=_make_pass_verification())

    policy_engine = PolicyEngine()

    return WorkflowExecutor(
        uow=uow,
        tool_registry=tool_registry,
        planner=planner,
        executor_agent=executor_agent,
        critic=critic,
        policy_engine=policy_engine,
    )


def _run_executor_and_capture_emitter(db_engine, pii_allow: bool):
    """Run executor for a flow with given pii.allow and capture the EventEmitter created."""
    flow_id = f"flow-pii-{pii_allow}"
    run_id = f"run-pii-{pii_allow}"

    with Session(db_engine) as session:
        _setup_flow_and_run(session, flow_id, run_id, pii_allow=pii_allow)

    # Set up planner and critic
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
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            executor = _build_executor(uow, planner, critic)

            with patch("saz.engine.executor.EventEmitter") as MockEmitter:
                mock_instance = MagicMock()
                mock_instance.commit_and_broadcast = AsyncMock()
                MockEmitter.return_value = mock_instance

                asyncio.run(executor.execute_run(run_id))

                return MockEmitter.call_args_list
    finally:
        session.close()


# ---------------------------------------------------------------------------
# PII policy flows from DSL through executor into EventEmitter
# ---------------------------------------------------------------------------


def test_pii_allow_false_gives_redact(db_engine):
    """When DSL has pii.allow: false, EventEmitter should get pii_policy='redact'."""
    call_args_list = _run_executor_and_capture_emitter(db_engine, pii_allow=False)

    found = False
    for call in call_args_list:
        kwargs = call.kwargs
        if kwargs.get("pii_policy") == "redact":
            found = True
            break
    assert found, f"Expected pii_policy='redact' in EventEmitter calls: {call_args_list}"


def test_pii_allow_true_gives_allow(db_engine):
    """When DSL has pii.allow: true, EventEmitter should get pii_policy='allow'."""
    call_args_list = _run_executor_and_capture_emitter(db_engine, pii_allow=True)

    found = False
    for call in call_args_list:
        kwargs = call.kwargs
        if kwargs.get("pii_policy") == "allow":
            found = True
            break
    assert found, f"Expected pii_policy='allow' in EventEmitter calls: {call_args_list}"


# ---------------------------------------------------------------------------
# ReplanRequired causes run to fail
# ---------------------------------------------------------------------------


def test_post_execution_replan_verdict_fails_run(db_engine):
    """Post-execution REPLAN verdict -> run marked as failed (tool already ran)."""
    flow_id = "flow-replan"
    run_id = "run-replan"

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

    replan_critique = _make_critique(Verdict.REPLAN)
    replan_critique.reasoning = "Output format does not match expected schema"
    critic = MagicMock()
    critic.critique = AsyncMock(return_value=replan_critique)
    # Pre-execution verification passes
    critic.verify_proposal = AsyncMock(return_value=_make_pass_verification())

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            executor = _build_executor(uow, planner, critic)
            asyncio.run(executor.execute_run(run_id))

        # Verify run is marked as failed (post-execution replan → CritiqueFailure)
        session2 = TestSession()
        try:
            run = session2.query(Run).filter_by(id=run_id).one()
            assert run.status == "failed", f"Expected 'failed', got '{run.status}'"
            assert run.error is not None
            assert run.error["type"] == "CritiqueFailure"
            assert "replan" in run.error["message"].lower()
        finally:
            session2.close()
    finally:
        session.close()
