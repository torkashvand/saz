"""Integration tests proving that suspension steps stop in-process execution.

Regression tests for the bug where _execute_human_approval and
_execute_webhook_wait returned a result dict that the main loop treated
as successful step completion, allowing subsequent steps to execute
before any resume/callback occurred.
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
from saz.db.models import Flow, Run, Step
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.tools.registry import ToolRegistry
from tests.conftest import TEST_USER_ID

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan(steps):
    return ExecutionPlan(
        plan_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        steps=steps,
        estimated_cost_usd=0.001,
        estimated_time_seconds=1,
        reasoning="test plan",
    )


def _make_critique(verdict, reasoning="ok", confidence=0.9):
    return Critique(
        verdict=verdict,
        reasoning=reasoning,
        issues=[] if verdict == Verdict.PASS else ["issue"],
        safety_flags=[],
        suggestions={},
        confidence=confidence,
    )


def _setup_flow_and_run(session, flow_id, run_id, steps_def, status="queued"):
    flow = Flow(
        created_by_user_id=TEST_USER_ID,
        id=flow_id,
        name="test-flow",
        definition={
            "workflow": {
                "planner_mode": "deterministic",
                "steps": steps_def,
            },
            "policies": {"budget_usd": 1.0},
        },
    )
    run = Run(
        created_by_user_id=TEST_USER_ID,
        id=run_id,
        flow_id=flow_id,
        status=status,
        planner_mode="deterministic",
        payload={"text": "hello"},
    )
    session.add_all([flow, run])
    session.commit()


def _build_executor(uow, planner, critic, tool_execute_mock):
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


def _make_committing_emitter(uow):
    """Create a mock emitter factory whose commit_and_broadcast calls uow.commit()."""

    def factory(*args, **kwargs):
        mock_emitter = MagicMock()

        async def commit_and_broadcast():
            uow.commit()

        mock_emitter.commit_and_broadcast = AsyncMock(side_effect=commit_and_broadcast)
        return mock_emitter

    return factory


# ---------------------------------------------------------------------------
# A. Human approval suspension stops execution
# ---------------------------------------------------------------------------


def test_human_approval_stops_execution(db_engine):
    """Executor stops at human.approval step. Next step never runs."""
    flow_id = "flow-approval-stop"
    run_id = "run-approval-stop"

    steps_def = [
        {"id": "s1", "type": "ai.extract", "instruction": "Extract"},
        {"id": "s2", "type": "human.approval", "description": "Approve"},
        {"id": "s3", "type": "ai.extract", "instruction": "Post-approval work"},
    ]

    with Session(db_engine) as session:
        _setup_flow_and_run(session, flow_id, run_id, steps_def)

    plan = _make_plan(
        [
            PlanStep(
                step_id="s1",
                step_type="ai.extract",
                reasoning="Extract data",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="s2",
                step_type="human.approval",
                reasoning="Needs human review",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="s3",
                step_type="ai.extract",
                reasoning="Post-approval step",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
        ]
    )

    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_execute = AsyncMock(
        return_value={"result": "extracted", "usage": {"tokens": 10, "cost_usd": 0.001}}
    )

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            with patch(
                "saz.engine.executor.EventEmitter",
                side_effect=_make_committing_emitter(uow),
            ):
                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        # Verify: tool was called ONCE (for s1 only, not for s3)
        assert (
            tool_execute.call_count == 1
        ), f"Expected tool called once (s1 only), but was called {tool_execute.call_count} times"

        # Verify: run is suspended
        session2 = TestSession()
        try:
            run = session2.query(Run).filter_by(id=run_id).one()
            assert run.status == "suspended"
            assert run.error is not None
            assert run.error["type"] == "HumanApprovalRequired"
            assert run.error["step_id"] == "s2"
            assert "callback_id" in run.error

            # Verify: s1 completed, s2 suspended, s3 never created
            steps = session2.query(Step).filter_by(run_id=run_id).order_by(Step.number).all()
            step_statuses = {s.name: s.status for s in steps}
            assert step_statuses["s1"] == "completed"
            assert step_statuses["s2"] == "suspended"
            assert (
                "s3" not in step_statuses
            ), "Step s3 should not exist — executor should have stopped"
        finally:
            session2.close()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# B. Webhook wait suspension stops execution
# ---------------------------------------------------------------------------


def test_webhook_wait_stops_execution(db_engine):
    """Executor stops at webhook.wait step. Next step never runs."""
    flow_id = "flow-webhook-stop"
    run_id = "run-webhook-stop"

    steps_def = [
        {"id": "s1", "type": "ai.extract", "instruction": "Extract"},
        {"id": "s2", "type": "webhook.wait", "params": {"event_name": "payment_confirmed"}},
        {"id": "s3", "type": "ai.extract", "instruction": "After webhook"},
    ]

    with Session(db_engine) as session:
        _setup_flow_and_run(session, flow_id, run_id, steps_def)

    plan = _make_plan(
        [
            PlanStep(
                step_id="s1",
                step_type="ai.extract",
                reasoning="Extract data",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="s2",
                step_type="webhook.wait",
                reasoning="Wait for payment",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="s3",
                step_type="ai.extract",
                reasoning="Continue after webhook",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
        ]
    )

    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_execute = AsyncMock(
        return_value={"result": "extracted", "usage": {"tokens": 10, "cost_usd": 0.001}}
    )

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            with patch(
                "saz.engine.executor.EventEmitter",
                side_effect=_make_committing_emitter(uow),
            ):
                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        # Tool called once (s1 only)
        assert tool_execute.call_count == 1

        session2 = TestSession()
        try:
            run = session2.query(Run).filter_by(id=run_id).one()
            assert run.status == "suspended"
            assert run.error["type"] == "WebhookWait"
            assert run.error["step_id"] == "s2"
            assert "callback_id" in run.error

            steps = session2.query(Step).filter_by(run_id=run_id).order_by(Step.number).all()
            step_statuses = {s.name: s.status for s in steps}
            assert step_statuses["s1"] == "completed"
            assert step_statuses["s2"] == "suspended"
            assert "s3" not in step_statuses
        finally:
            session2.close()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# C. Resume after human approval continues correctly
# ---------------------------------------------------------------------------


def test_resume_after_approval_continues_from_correct_step(db_engine):
    """After resume, execution continues from the step after approval, not from the start."""
    flow_id = "flow-resume-approval"
    run_id = "run-resume-approval"

    steps_def = [
        {"id": "s1", "type": "ai.extract", "instruction": "Extract"},
        {"id": "s2", "type": "human.approval", "description": "Approve"},
        {"id": "s3", "type": "ai.extract", "instruction": "Post-approval"},
    ]

    # Phase 1: Set up flow and run with s1 completed, s2 completed (approved), run queued
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id=flow_id,
            name="test-flow",
            definition={
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": steps_def,
                },
                "policies": {"budget_usd": 1.0},
            },
        )
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id=run_id,
            flow_id=flow_id,
            status="queued",  # Will be set to running by executor
            planner_mode="deterministic",
            payload={"text": "hello"},
        )
        # Pre-populate completed steps (simulating resume after approval)
        step1 = Step(
            id="step-db-1",
            run_id=run_id,
            number=0,
            name="s1",
            step_type="ai.extract",
            status="completed",
            output={"result": "extracted_data"},
        )
        step2 = Step(
            id="step-db-2",
            run_id=run_id,
            number=1,
            name="s2",
            step_type="human.approval",
            status="completed",
            output={"approved": True, "approver": "admin@example.com"},
        )
        session.add_all([flow, run, step1, step2])
        session.commit()

    plan = _make_plan(
        [
            PlanStep(
                step_id="s1",
                step_type="ai.extract",
                reasoning="Extract data",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="s2",
                step_type="human.approval",
                reasoning="Approve",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="s3",
                step_type="ai.extract",
                reasoning="Post-approval",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
        ]
    )

    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_execute = AsyncMock(
        return_value={"result": "post_approval_result", "usage": {"tokens": 10, "cost_usd": 0.001}}
    )

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            with patch(
                "saz.engine.executor.EventEmitter",
                side_effect=_make_committing_emitter(uow),
            ):
                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        # Tool called once — only for s3 (s1 and s2 were skipped as already completed)
        assert tool_execute.call_count == 1

        session2 = TestSession()
        try:
            run = session2.query(Run).filter_by(id=run_id).one()
            assert run.status == "completed"

            # s3 should now exist and be completed
            s3 = session2.query(Step).filter_by(run_id=run_id, name="s3").first()
            assert s3 is not None
            assert s3.status == "completed"
        finally:
            session2.close()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# D. Resume after webhook callback continues correctly
# ---------------------------------------------------------------------------


def test_resume_after_webhook_continues_from_correct_step(db_engine):
    """After webhook resume, execution continues from step after webhook.wait."""
    flow_id = "flow-resume-webhook"
    run_id = "run-resume-webhook"

    steps_def = [
        {"id": "s1", "type": "ai.extract", "instruction": "Extract"},
        {"id": "s2", "type": "webhook.wait", "params": {"event_name": "payment"}},
        {"id": "s3", "type": "ai.extract", "instruction": "After webhook"},
    ]

    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id=flow_id,
            name="test-flow",
            definition={
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": steps_def,
                },
                "policies": {"budget_usd": 1.0},
            },
        )
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id=run_id,
            flow_id=flow_id,
            status="queued",
            planner_mode="deterministic",
            payload={"text": "hello"},
        )
        step1 = Step(
            id="step-wh-1",
            run_id=run_id,
            number=0,
            name="s1",
            step_type="ai.extract",
            status="completed",
            output={"result": "extracted"},
        )
        step2 = Step(
            id="step-wh-2",
            run_id=run_id,
            number=1,
            name="s2",
            step_type="webhook.wait",
            status="completed",
            output={"callback_received": True, "data": {"payment_id": "PAY-123"}},
        )
        session.add_all([flow, run, step1, step2])
        session.commit()

    plan = _make_plan(
        [
            PlanStep(
                step_id="s1",
                step_type="ai.extract",
                reasoning="Extract",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="s2",
                step_type="webhook.wait",
                reasoning="Wait",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="s3",
                step_type="ai.extract",
                reasoning="Continue",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
        ]
    )

    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_execute = AsyncMock(
        return_value={"result": "after_webhook", "usage": {"tokens": 10, "cost_usd": 0.001}}
    )

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            with patch(
                "saz.engine.executor.EventEmitter",
                side_effect=_make_committing_emitter(uow),
            ):
                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        # Only s3 should have executed
        assert tool_execute.call_count == 1

        session2 = TestSession()
        try:
            run = session2.query(Run).filter_by(id=run_id).one()
            assert run.status == "completed"
        finally:
            session2.close()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# E. Event ordering around suspension
# ---------------------------------------------------------------------------


def test_event_ordering_around_human_approval_suspension(db_engine):
    """Events emitted around suspension are correct: no premature completion or progress."""
    flow_id = "flow-events-approval"
    run_id = "run-events-approval"

    steps_def = [
        {"id": "s1", "type": "ai.extract", "instruction": "Extract"},
        {"id": "s2", "type": "human.approval", "description": "Approve"},
        {"id": "s3", "type": "ai.extract", "instruction": "After approval"},
    ]

    with Session(db_engine) as session:
        _setup_flow_and_run(session, flow_id, run_id, steps_def)

    plan = _make_plan(
        [
            PlanStep(
                step_id="s1",
                step_type="ai.extract",
                reasoning="Extract",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="s2",
                step_type="human.approval",
                reasoning="Review",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="s3",
                step_type="ai.extract",
                reasoning="Post-approval",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
        ]
    )

    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_execute = AsyncMock(
        return_value={"result": "ok", "usage": {"tokens": 10, "cost_usd": 0.001}}
    )

    # Track emitter method calls
    emitter_calls = []

    def tracking_emitter_factory(uow):
        def factory(*args, **kwargs):
            mock_emitter = MagicMock()

            async def commit_and_broadcast():
                uow.commit()

            mock_emitter.commit_and_broadcast = AsyncMock(side_effect=commit_and_broadcast)

            # Track important event methods
            for method_name in [
                "step_started",
                "step_completed",
                "step_failed",
                "approval_requested",
                "run_suspended",
                "run_completed",
                "progress_updated",
            ]:
                original = getattr(mock_emitter, method_name)

                def make_tracker(name, orig):
                    def tracker(*a, **kw):
                        emitter_calls.append(name)
                        return orig(*a, **kw)

                    return tracker

                setattr(mock_emitter, method_name, make_tracker(method_name, original))

            return mock_emitter

        return factory

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            with patch(
                "saz.engine.executor.EventEmitter",
                side_effect=tracking_emitter_factory(uow),
            ):
                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        # Verify event ordering
        # Expected: s1 events, then s2 approval/suspension, NO s2 step_completed, NO s3 events
        assert "step_started" in emitter_calls  # s1 started
        assert "step_completed" in emitter_calls  # s1 completed
        assert "approval_requested" in emitter_calls
        assert "run_suspended" in emitter_calls

        # After approval_requested, there should be run_suspended but NOT
        # step_completed for s2 (the approval step should not be marked completed)
        approval_idx = emitter_calls.index("approval_requested")
        suspended_idx = emitter_calls.index("run_suspended")
        assert suspended_idx > approval_idx, "run_suspended must come after approval_requested"

        # No step_completed after the approval_requested (s2 should stay suspended)
        events_after_approval = emitter_calls[approval_idx:]
        assert (
            "step_completed" not in events_after_approval
        ), "No step_completed should be emitted after the approval step starts"

        # No progress_updated after suspension
        assert (
            "progress_updated" not in events_after_approval
        ), "No progress_updated should be emitted for the suspended step"

        # run_completed should NOT appear — run is suspended, not completed
        assert "run_completed" not in emitter_calls

    finally:
        session.close()


# ---------------------------------------------------------------------------
# F. State persistence during suspension
# ---------------------------------------------------------------------------


def test_state_persistence_during_suspension(db_engine):
    """DB state is correct while run is suspended at approval."""
    flow_id = "flow-state-suspend"
    run_id = "run-state-suspend"

    steps_def = [
        {"id": "s1", "type": "ai.extract", "instruction": "Extract"},
        {"id": "s2", "type": "human.approval", "description": "Approve"},
    ]

    with Session(db_engine) as session:
        _setup_flow_and_run(session, flow_id, run_id, steps_def)

    plan = _make_plan(
        [
            PlanStep(
                step_id="s1",
                step_type="ai.extract",
                reasoning="Extract",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="s2",
                step_type="human.approval",
                reasoning="Approve",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
        ]
    )

    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_execute = AsyncMock(
        return_value={"result": "ok", "usage": {"tokens": 10, "cost_usd": 0.001}}
    )

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            with patch(
                "saz.engine.executor.EventEmitter",
                side_effect=_make_committing_emitter(uow),
            ):
                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        session2 = TestSession()
        try:
            # Run is suspended
            run = session2.query(Run).filter_by(id=run_id).one()
            assert run.status == "suspended"
            assert run.error is not None
            assert run.error["type"] == "HumanApprovalRequired"

            # callback_id is present for webhook resumption
            assert "callback_id" in run.error
            assert len(run.error["callback_id"]) == 32  # UUID hex

            # Step statuses
            steps = session2.query(Step).filter_by(run_id=run_id).order_by(Step.number).all()
            assert len(steps) == 2
            assert steps[0].name == "s1"
            assert steps[0].status == "completed"
            assert steps[0].output is not None

            assert steps[1].name == "s2"
            assert steps[1].status == "suspended"
            # Suspended step should not have output yet (awaiting approval)
            assert steps[1].output is None
        finally:
            session2.close()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# G. Regression test: exact reported bug shape
# ---------------------------------------------------------------------------


def test_regression_suspended_but_next_step_still_runs(db_engine):
    """Regression: steps 0-2 succeed, step 3 is approval, step 4 must NOT execute.

    Before the fix, the executor would mark the run as suspended but continue
    executing step 4 in-process, which would fail on a missing secret or
    create unintended side effects.
    """
    flow_id = "flow-regression"
    run_id = "run-regression"

    steps_def = [
        {"id": "extract_data", "type": "ai.extract", "instruction": "Extract"},
        {"id": "route_ticket", "type": "ai.extract", "instruction": "Route"},
        {"id": "score_complexity", "type": "ai.extract", "instruction": "Score"},
        {"id": "approve_action", "type": "human.approval", "description": "Review"},
        {"id": "send_email", "type": "ai.extract", "instruction": "Send (must not run)"},
    ]

    with Session(db_engine) as session:
        _setup_flow_and_run(session, flow_id, run_id, steps_def)

    plan = _make_plan(
        [
            PlanStep(
                step_id="extract_data",
                step_type="ai.extract",
                reasoning="Extract",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="route_ticket",
                step_type="ai.extract",
                reasoning="Route",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="score_complexity",
                step_type="ai.extract",
                reasoning="Score",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="approve_action",
                step_type="human.approval",
                reasoning="Review",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="send_email",
                step_type="ai.extract",
                reasoning="Send",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
        ]
    )

    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_execute = AsyncMock(
        return_value={"result": "ok", "usage": {"tokens": 10, "cost_usd": 0.001}}
    )

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            with patch(
                "saz.engine.executor.EventEmitter",
                side_effect=_make_committing_emitter(uow),
            ):
                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        # Tool was called 3 times: extract_data, route_ticket, score_complexity
        # NOT for send_email
        assert tool_execute.call_count == 3, (
            f"Expected 3 tool calls (steps 0-2), got {tool_execute.call_count}. "
            "If 4, the bug is back: send_email ran despite approval gate."
        )

        session2 = TestSession()
        try:
            run = session2.query(Run).filter_by(id=run_id).one()
            assert run.status == "suspended"

            steps = session2.query(Step).filter_by(run_id=run_id).order_by(Step.number).all()
            step_names = [s.name for s in steps]

            # Steps 0-2 completed, step 3 suspended, step 4 never created
            assert "extract_data" in step_names
            assert "route_ticket" in step_names
            assert "score_complexity" in step_names
            assert "approve_action" in step_names
            assert "send_email" not in step_names, (
                "send_email step should never have been created — " "executor must stop at approval"
            )

            # approve_action should be suspended, not completed
            approve_step = next(s for s in steps if s.name == "approve_action")
            assert approve_step.status == "suspended"
        finally:
            session2.close()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# H. Suspension followed by rejection
# ---------------------------------------------------------------------------


def test_suspension_step_at_first_position(db_engine):
    """Approval step as the very first step still suspends correctly."""
    flow_id = "flow-first-approval"
    run_id = "run-first-approval"

    steps_def = [
        {"id": "s1", "type": "human.approval", "description": "Pre-approve"},
        {"id": "s2", "type": "ai.extract", "instruction": "Work"},
    ]

    with Session(db_engine) as session:
        _setup_flow_and_run(session, flow_id, run_id, steps_def)

    plan = _make_plan(
        [
            PlanStep(
                step_id="s1",
                step_type="human.approval",
                reasoning="Pre-approve",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
            PlanStep(
                step_id="s2",
                step_type="ai.extract",
                reasoning="Work",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            ),
        ]
    )

    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_execute = AsyncMock(
        return_value={"result": "ok", "usage": {"tokens": 10, "cost_usd": 0.001}}
    )

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()

    try:
        with UnitOfWork(session) as uow:
            with patch(
                "saz.engine.executor.EventEmitter",
                side_effect=_make_committing_emitter(uow),
            ):
                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        # No tool should have executed at all
        assert tool_execute.call_count == 0

        session2 = TestSession()
        try:
            run = session2.query(Run).filter_by(id=run_id).one()
            assert run.status == "suspended"

            steps = session2.query(Step).filter_by(run_id=run_id).all()
            assert len(steps) == 1  # Only s1 created
            assert steps[0].name == "s1"
            assert steps[0].status == "suspended"
        finally:
            session2.close()
    finally:
        session.close()
