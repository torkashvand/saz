"""Integration tests for tool attempt numbering in emitted events.

Proves that:
- tool.started events emit increasing attempt numbers across retries (1, 2, 3)
- tool.failed and tool.succeeded events include the correct attempt number
- non-retried steps still show attempt 1
- step.retry_count is updated to reflect the number of retries consumed
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.orm import sessionmaker

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


# Single-step plan with max_retries=3 (4 total attempts)
RETRYABLE_PLAN_STEP = PlanStep(
    step_id="call_api",
    step_type="tool.call",
    reasoning="Call external API",
    error_handling=ErrorHandling.RETRY,
    max_retries=3,
)


def _setup_run(session, flow_id, run_id):
    """Create a flow and queued run."""
    flow = Flow(
        id=flow_id,
        name=f"test-flow-{flow_id}",
        definition={
            "workflow": {
                "planner_mode": "deterministic",
                "steps": [
                    {
                        "id": "call_api",
                        "type": "tool.call",
                        "tool": "http_request",
                        "input_template": {},
                    },
                ],
            },
            "policies": {"budget_usd": 1.0},
        },
    )
    run = Run(
        id=run_id,
        flow_id=flow_id,
        status="queued",
        planner_mode="deterministic",
        payload={"data": "test"},
    )
    session.add_all([flow, run])
    session.commit()


def _build_executor(uow, planner, critic, tool_execute_mock):
    executor_agent = MagicMock(spec=ExecutorAgent)
    executor_agent.ground.return_value = ToolCall(
        tool="http_request",
        arguments={"method": "POST", "url": "http://example.com/api"},
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
    """Create a mock emitter factory that captures emitted events."""
    emitted_events = []

    def factory(*args, **kwargs):
        mock_emitter = MagicMock()

        async def commit_and_broadcast():
            uow.commit()

        mock_emitter.commit_and_broadcast = AsyncMock(side_effect=commit_and_broadcast)

        # Capture tool_started calls with their attempt parameter
        original_tool_started = MagicMock()

        def track_tool_started(**kw):
            emitted_events.append(("tool.started", kw))
            return original_tool_started(**kw)

        mock_emitter.tool_started = MagicMock(side_effect=track_tool_started)

        # Capture tool_failed calls
        def track_tool_failed(**kw):
            emitted_events.append(("tool.failed", kw))

        mock_emitter.tool_failed = MagicMock(side_effect=track_tool_failed)

        # Capture tool_succeeded calls
        def track_tool_succeeded(**kw):
            emitted_events.append(("tool.succeeded", kw))

        mock_emitter.tool_succeeded = MagicMock(side_effect=track_tool_succeeded)

        return mock_emitter

    return factory, emitted_events


# ---------------------------------------------------------------------------
# 1. Tool retries emit increasing attempt numbers
# ---------------------------------------------------------------------------


def test_tool_retries_emit_increasing_attempt_numbers(db_engine):
    """When a tool fails and is retried, each tool.started event must show
    an increasing attempt number (1, 2, 3), not repeated 'attempt 1'."""
    flow_id = "flow-attempt-num"
    run_id = "run-attempt-num"

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    try:
        _setup_run(session, flow_id, run_id)
    finally:
        session.close()

    # Tool fails on attempts 1-2, succeeds on attempt 3
    call_count = [0]

    async def fail_then_succeed(**kwargs):
        call_count[0] += 1
        if call_count[0] <= 2:
            raise RuntimeError(f"Connection failed (attempt {call_count[0]})")
        return {"result": "ok", "usage": {"tokens": 10, "cost_usd": 0.001}}

    tool_execute = AsyncMock(side_effect=fail_then_succeed)

    plan = _make_plan([RETRYABLE_PLAN_STEP])
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    session2 = TestSession()
    try:
        with UnitOfWork(session2) as uow:
            emitter_factory, emitted = _make_committing_emitter(uow)
            with patch("saz.engine.executor.EventEmitter", side_effect=emitter_factory):
                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        # Extract tool.started events
        tool_started_events = [e for e in emitted if e[0] == "tool.started"]

        # Must have 3 tool.started events with attempts 1, 2, 3
        assert (
            len(tool_started_events) == 3
        ), f"Expected 3 tool.started events, got {len(tool_started_events)}"
        attempts = [e[1]["attempt"] for e in tool_started_events]
        assert attempts == [1, 2, 3], f"Expected attempt sequence [1, 2, 3], got {attempts}"

        # tool.failed events should also have correct attempts
        tool_failed_events = [e for e in emitted if e[0] == "tool.failed"]
        assert len(tool_failed_events) == 2
        failed_attempts = [e[1]["attempt"] for e in tool_failed_events]
        assert failed_attempts == [1, 2]

        # tool.succeeded should show attempt 3
        tool_succeeded_events = [e for e in emitted if e[0] == "tool.succeeded"]
        assert len(tool_succeeded_events) == 1
        assert tool_succeeded_events[0][1]["attempt"] == 3
    finally:
        session2.close()


# ---------------------------------------------------------------------------
# 2. Non-retried step shows attempt 1
# ---------------------------------------------------------------------------


def test_non_retried_step_shows_attempt_1(db_engine):
    """A step that succeeds on the first try should show attempt 1."""
    flow_id = "flow-no-retry"
    run_id = "run-no-retry"

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    try:
        _setup_run(session, flow_id, run_id)
    finally:
        session.close()

    tool_execute = AsyncMock(
        return_value={"result": "ok", "usage": {"tokens": 10, "cost_usd": 0.001}}
    )

    plan = _make_plan([RETRYABLE_PLAN_STEP])
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    session2 = TestSession()
    try:
        with UnitOfWork(session2) as uow:
            emitter_factory, emitted = _make_committing_emitter(uow)
            with patch("saz.engine.executor.EventEmitter", side_effect=emitter_factory):
                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        tool_started_events = [e for e in emitted if e[0] == "tool.started"]
        assert len(tool_started_events) == 1
        assert tool_started_events[0][1]["attempt"] == 1
    finally:
        session2.close()


# ---------------------------------------------------------------------------
# 3. Final failure after max retries shows correct attempt number
# ---------------------------------------------------------------------------


def test_final_failure_shows_correct_attempt_number(db_engine):
    """When all retries are exhausted, the last tool.failed event must show
    the correct final attempt number."""
    flow_id = "flow-max-retry"
    run_id = "run-max-retry"

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    try:
        _setup_run(session, flow_id, run_id)
    finally:
        session.close()

    # Always fail
    tool_execute = AsyncMock(side_effect=RuntimeError("Always fails"))

    plan = _make_plan([RETRYABLE_PLAN_STEP])
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    session2 = TestSession()
    try:
        with UnitOfWork(session2) as uow:
            emitter_factory, emitted = _make_committing_emitter(uow)
            with patch("saz.engine.executor.EventEmitter", side_effect=emitter_factory):
                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        # 4 attempts total (max_retries=3 → 4 attempts)
        tool_started_events = [e for e in emitted if e[0] == "tool.started"]
        assert len(tool_started_events) == 4
        attempts = [e[1]["attempt"] for e in tool_started_events]
        assert attempts == [1, 2, 3, 4]

        tool_failed_events = [e for e in emitted if e[0] == "tool.failed"]
        assert len(tool_failed_events) == 4
        failed_attempts = [e[1]["attempt"] for e in tool_failed_events]
        assert failed_attempts == [1, 2, 3, 4]
    finally:
        session2.close()


# ---------------------------------------------------------------------------
# 4. Step retry_count is updated during retries
# ---------------------------------------------------------------------------


def test_step_retry_count_updated(db_engine):
    """After retries, the persisted step.retry_count reflects how many
    retries were consumed (0-based: 0 on first attempt, N-1 after N retries)."""
    flow_id = "flow-retry-count"
    run_id = "run-retry-count"

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    try:
        _setup_run(session, flow_id, run_id)
    finally:
        session.close()

    # Fail twice, succeed on third attempt
    call_count = [0]

    async def fail_twice(**kwargs):
        call_count[0] += 1
        if call_count[0] <= 2:
            raise RuntimeError("Transient failure")
        return {"result": "ok", "usage": {"tokens": 10, "cost_usd": 0.001}}

    tool_execute = AsyncMock(side_effect=fail_twice)

    plan = _make_plan([RETRYABLE_PLAN_STEP])
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    session2 = TestSession()
    try:
        with UnitOfWork(session2) as uow:
            emitter_factory, _ = _make_committing_emitter(uow)
            with patch("saz.engine.executor.EventEmitter", side_effect=emitter_factory):
                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        # Check persisted step
        session3 = TestSession()
        try:
            step = session3.query(Step).filter_by(run_id=run_id, name="call_api").one()
            # retry_count reflects the last failed attempt index (0-based)
            # After 2 failures, retry_count should be 1 (index of last failure)
            # because the step eventually succeeded so the last update was attempt=1
            assert (
                step.retry_count == 1
            ), f"Expected retry_count=1 after 2 failures, got {step.retry_count}"
            assert step.status == "completed"
        finally:
            session3.close()
    finally:
        session2.close()
