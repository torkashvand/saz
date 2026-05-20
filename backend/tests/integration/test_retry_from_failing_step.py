"""Integration tests for same-run retry semantics.

Proves that:
- retry() keeps the same run_id and resets it to queued
- historical step attempts are preserved (not deleted)
- the executor restores context only from the latest attempt per step
- the executor skips already-completed steps and re-executes from the failing point
- error summary uses the latest attempt's failure, not stale historical ones
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
from saz.domain.error_enrichment import ErrorEnrichmentService
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.services.run_service import RunService
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


STEPS_DEF = [
    {"id": "extract", "type": "ai.extract", "instruction": "Extract data"},
    {"id": "validate", "type": "ai.extract", "instruction": "Validate data"},
    {"id": "draft", "type": "ai.extract", "instruction": "Draft output"},
    {"id": "send", "type": "tool.call", "tool": "http_request", "input_template": {}},
]

PLAN_STEPS = [
    PlanStep(
        step_id="extract",
        step_type="ai.extract",
        reasoning="Extract",
        error_handling=ErrorHandling.FAIL,
        max_retries=0,
    ),
    PlanStep(
        step_id="validate",
        step_type="ai.extract",
        reasoning="Validate",
        error_handling=ErrorHandling.FAIL,
        max_retries=0,
    ),
    PlanStep(
        step_id="draft",
        step_type="ai.extract",
        reasoning="Draft",
        error_handling=ErrorHandling.FAIL,
        max_retries=0,
    ),
    PlanStep(
        step_id="send",
        step_type="tool.call",
        reasoning="Send",
        error_handling=ErrorHandling.FAIL,
        max_retries=0,
    ),
]


def _setup_failed_run(session, flow_id, run_id, failing_step_number=2):
    """Create a flow and a failed run where steps 0..failing-1 completed."""
    flow = Flow(
        created_by_user_id=TEST_USER_ID,
        id=flow_id,
        name=f"test-flow-{flow_id}",
        definition={
            "workflow": {
                "planner_mode": "deterministic",
                "steps": STEPS_DEF,
            },
            "policies": {"budget_usd": 1.0},
        },
    )
    run = Run(
        created_by_user_id=TEST_USER_ID,
        id=run_id,
        flow_id=flow_id,
        status="failed",
        planner_mode="deterministic",
        payload={"text": "hello"},
        error={"message": "step failed", "type": "ToolExecutionError"},
    )
    entities = [flow, run]

    step_defs = [
        ("extract", "ai.extract"),
        ("validate", "ai.extract"),
        ("draft", "ai.extract"),
        ("send", "tool.call"),
    ]
    for i, (name, stype) in enumerate(step_defs):
        if i < failing_step_number:
            step = Step(
                run_id=run_id,
                number=i,
                name=name,
                step_type=stype,
                status="completed",
                attempt=1,
                output={"result": f"{name}_output"},
            )
            entities.append(step)
        elif i == failing_step_number:
            step = Step(
                run_id=run_id,
                number=i,
                name=name,
                step_type=stype,
                status="failed",
                attempt=1,
                error={"message": f"{name} failed"},
            )
            entities.append(step)

    session.add_all(entities)
    session.commit()


def _build_executor(uow, planner, critic, tool_execute_mock):
    executor_agent = MagicMock(spec=ExecutorAgent)
    executor_agent.ground.return_value = ToolCall(
        tool="ai.extract",
        arguments={"instruction": "test", "data": {"text": "hello"}},
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
# 1. Same-run retry: same run_id, no new run created
# ---------------------------------------------------------------------------


def test_retry_keeps_same_run_id(db_engine):
    """retry() resets the same run to queued — no new run is created."""
    flow_id = "flow-retry-same"
    run_id = "run-retry-same"

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    try:
        _setup_failed_run(session, flow_id, run_id, failing_step_number=2)
    finally:
        session.close()

    session2 = TestSession()
    try:
        with UnitOfWork(session2) as uow:
            service = RunService(uow)
            service.retry(run_id)

        # Verify same run is now queued
        session3 = TestSession()
        try:
            run = session3.query(Run).filter_by(id=run_id).one()
            assert run.status == "queued"
            assert run.error is None
            assert run.completed_at is None

            # No other runs should exist for this flow
            all_runs = session3.query(Run).filter_by(flow_id=flow_id).all()
            assert len(all_runs) == 1
            assert all_runs[0].id == run_id
        finally:
            session3.close()
    finally:
        session2.close()


# ---------------------------------------------------------------------------
# 2. Same-run retry preserves history
# ---------------------------------------------------------------------------


def test_retry_preserves_step_history(db_engine):
    """retry() does not delete or mutate existing step records."""
    flow_id = "flow-retry-hist"
    run_id = "run-retry-hist"

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    try:
        _setup_failed_run(session, flow_id, run_id, failing_step_number=2)
    finally:
        session.close()

    session2 = TestSession()
    try:
        with UnitOfWork(session2) as uow:
            service = RunService(uow)
            service.retry(run_id)

        session3 = TestSession()
        try:
            steps = (
                session3.query(Step)
                .filter_by(run_id=run_id)
                .order_by(Step.number, Step.attempt)
                .all()
            )
            # Original 3 steps remain: 2 completed + 1 failed
            assert len(steps) == 3
            assert steps[0].name == "extract"
            assert steps[0].status == "completed"
            assert steps[0].attempt == 1
            assert steps[1].name == "validate"
            assert steps[1].status == "completed"
            assert steps[1].attempt == 1
            assert steps[2].name == "draft"
            assert steps[2].status == "failed"
            assert steps[2].attempt == 1
        finally:
            session3.close()
    finally:
        session2.close()


# ---------------------------------------------------------------------------
# 3. Executor skips completed steps and re-executes from failing step
# ---------------------------------------------------------------------------


def test_executor_retries_from_failing_step(db_engine):
    """After retry, executor skips completed steps and runs from the failing step."""
    flow_id = "flow-retry-exec"
    run_id = "run-retry-exec"

    TestSession = sessionmaker(bind=db_engine)

    # Set up failed run (failed at step 2 = "draft")
    session = TestSession()
    try:
        _setup_failed_run(session, flow_id, run_id, failing_step_number=2)
    finally:
        session.close()

    # Retry (resets to queued)
    session2 = TestSession()
    try:
        with UnitOfWork(session2) as uow:
            service = RunService(uow)
            service.retry(run_id)
    finally:
        session2.close()

    # Run executor
    plan = _make_plan(PLAN_STEPS)
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_execute = AsyncMock(
        return_value={"result": "ok", "usage": {"tokens": 10, "cost_usd": 0.001}}
    )

    session3 = TestSession()
    try:
        with UnitOfWork(session3) as uow:
            with patch(
                "saz.engine.executor.EventEmitter",
                side_effect=_make_committing_emitter(uow),
            ):
                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        # Tool called 2 times: draft + send (extract and validate skipped)
        assert (
            tool_execute.call_count == 2
        ), f"Expected 2 tool calls (draft, send), got {tool_execute.call_count}"

        # Verify run completed
        session4 = TestSession()
        try:
            run = session4.query(Run).filter_by(id=run_id).one()
            assert run.status == "completed"

            steps = (
                session4.query(Step)
                .filter_by(run_id=run_id)
                .order_by(Step.number, Step.attempt)
                .all()
            )

            # Original steps: extract(completed,a1), validate(completed,a1), draft(failed,a1)
            # New steps from executor: draft(completed,a2), send(completed,a1)
            # Total: 5 step rows
            assert len(steps) == 5

            # extract: only attempt 1, completed
            extract_steps = [s for s in steps if s.name == "extract"]
            assert len(extract_steps) == 1
            assert extract_steps[0].status == "completed"
            assert extract_steps[0].attempt == 1

            # validate: only attempt 1, completed
            validate_steps = [s for s in steps if s.name == "validate"]
            assert len(validate_steps) == 1
            assert validate_steps[0].status == "completed"
            assert validate_steps[0].attempt == 1

            # draft: attempt 1 (failed) + attempt 2 (completed by executor)
            draft_steps = sorted([s for s in steps if s.name == "draft"], key=lambda s: s.attempt)
            assert len(draft_steps) == 2
            assert draft_steps[0].status == "failed"
            assert draft_steps[0].attempt == 1
            assert draft_steps[1].status == "completed"
            assert draft_steps[1].attempt == 2

            # send: attempt 1 (completed by executor — first time this step ran)
            send_steps = [s for s in steps if s.name == "send"]
            assert len(send_steps) == 1
            assert send_steps[0].status == "completed"
            assert send_steps[0].attempt == 1
        finally:
            session4.close()
    finally:
        session3.close()


# ---------------------------------------------------------------------------
# 4. Context restored from latest attempt only
# ---------------------------------------------------------------------------


def test_executor_restores_context_from_latest_attempt(db_engine):
    """If a step has multiple attempts, executor uses the latest completed attempt's output."""
    flow_id = "flow-ctx-latest"
    run_id = "run-ctx-latest"

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    try:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id=flow_id,
            name="test-ctx-latest",
            definition={
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": STEPS_DEF,
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
        # Simulate: extract had attempt 1 (failed) and attempt 2 (completed)
        step_old = Step(
            run_id=run_id,
            number=0,
            name="extract",
            step_type="ai.extract",
            status="failed",
            attempt=1,
            output={"result": "stale_output"},
            error={"message": "first try failed"},
        )
        step_new = Step(
            run_id=run_id,
            number=0,
            name="extract",
            step_type="ai.extract",
            status="completed",
            attempt=2,
            output={"result": "correct_output"},
        )
        # validate completed on attempt 1
        step_validate = Step(
            run_id=run_id,
            number=1,
            name="validate",
            step_type="ai.extract",
            status="completed",
            attempt=1,
            output={"result": "validate_output"},
        )
        session.add_all([flow, run, step_old, step_new, step_validate])
        session.commit()
    finally:
        session.close()

    # Run executor — should restore extract from attempt 2 (correct_output),
    # skip extract and validate, execute draft and send
    plan = _make_plan(PLAN_STEPS)
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_execute = AsyncMock(
        return_value={"result": "ok", "usage": {"tokens": 10, "cost_usd": 0.001}}
    )

    session2 = TestSession()
    try:
        with UnitOfWork(session2) as uow:
            with patch(
                "saz.engine.executor.EventEmitter",
                side_effect=_make_committing_emitter(uow),
            ):
                executor = _build_executor(uow, planner, critic, tool_execute)
                asyncio.run(executor.execute_run(run_id))

        # Should execute 2 steps (draft + send), not 4
        assert tool_execute.call_count == 2
    finally:
        session2.close()


# ---------------------------------------------------------------------------
# 5. Retry on non-failed run raises ValueError
# ---------------------------------------------------------------------------


def test_retry_non_failed_run_raises(db_engine):
    """Retry of a non-failed run raises ValueError."""
    flow_id = "flow-retry-nonfailed"
    run_id = "run-retry-nonfailed"

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    try:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id=flow_id,
            name="test-retry-nonfailed",
            definition={"workflow": {"steps": []}, "policies": {"budget_usd": 1.0}},
        )
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id=run_id,
            flow_id=flow_id,
            status="completed",
            planner_mode="deterministic",
            payload={},
        )
        session.add_all([flow, run])
        session.commit()
    finally:
        session.close()

    session2 = TestSession()
    try:
        with UnitOfWork(session2) as uow:
            service = RunService(uow)
            try:
                service.retry(run_id)
                raise AssertionError("Should have raised ValueError")
            except ValueError as e:
                assert "Can only retry failed runs" in str(e)
    finally:
        session2.close()


# ---------------------------------------------------------------------------
# 6. Retry when failure is at step 0
# ---------------------------------------------------------------------------


def test_retry_failure_at_first_step(db_engine):
    """When the first step fails, retry resets run and preserves the failed step."""
    flow_id = "flow-retry-first"
    run_id = "run-retry-first"

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    try:
        _setup_failed_run(session, flow_id, run_id, failing_step_number=0)
    finally:
        session.close()

    session2 = TestSession()
    try:
        with UnitOfWork(session2) as uow:
            service = RunService(uow)
            service.retry(run_id)

        session3 = TestSession()
        try:
            run = session3.query(Run).filter_by(id=run_id).one()
            assert run.status == "queued"

            # Original failed step still exists
            steps = session3.query(Step).filter_by(run_id=run_id).all()
            assert len(steps) == 1
            assert steps[0].name == "extract"
            assert steps[0].status == "failed"
            assert steps[0].attempt == 1
        finally:
            session3.close()
    finally:
        session2.close()


# ---------------------------------------------------------------------------
# 7. Double retry — attempt numbers increment correctly each time
# ---------------------------------------------------------------------------


def test_double_retry_increments_attempt_numbers(db_engine):
    """Two successive retries produce attempt 1 (failed), 2 (failed), 3 (completed).

    This proves that the executor correctly computes next_attempt from the
    max existing attempt, not just hardcoding attempt=1.
    """
    flow_id = "flow-double-retry"
    run_id = "run-double-retry"

    TestSession = sessionmaker(bind=db_engine)

    # Phase 1: create a failed run (failed at step 0 = "extract")
    session = TestSession()
    try:
        _setup_failed_run(session, flow_id, run_id, failing_step_number=0)
    finally:
        session.close()

    # Phase 2: first retry — run executor, make step fail again
    session2 = TestSession()
    try:
        with UnitOfWork(session2) as uow:
            service = RunService(uow)
            service.retry(run_id)
    finally:
        session2.close()

    plan = _make_plan(PLAN_STEPS)
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    # First retry: extract fails again
    call_count = [0]

    async def fail_on_extract(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("extract failed again")
        return {"result": "ok", "usage": {"tokens": 10, "cost_usd": 0.001}}

    tool_execute_1 = AsyncMock(side_effect=fail_on_extract)

    session3 = TestSession()
    try:
        with UnitOfWork(session3) as uow:
            with patch(
                "saz.engine.executor.EventEmitter",
                side_effect=_make_committing_emitter(uow),
            ):
                executor = _build_executor(uow, planner, critic, tool_execute_1)
                asyncio.run(executor.execute_run(run_id))
    finally:
        session3.close()

    # After first retry: run should be failed, extract has attempt 1 (failed) + attempt 2 (failed)
    session4 = TestSession()
    try:
        run = session4.query(Run).filter_by(id=run_id).one()
        assert run.status == "failed"

        extract_steps = (
            session4.query(Step)
            .filter_by(run_id=run_id, name="extract")
            .order_by(Step.attempt)
            .all()
        )
        assert len(extract_steps) == 2
        assert extract_steps[0].attempt == 1
        assert extract_steps[0].status == "failed"
        assert extract_steps[1].attempt == 2
        assert extract_steps[1].status == "failed"
    finally:
        session4.close()

    # Phase 3: second retry — extract succeeds this time
    session5 = TestSession()
    try:
        with UnitOfWork(session5) as uow:
            service = RunService(uow)
            service.retry(run_id)
    finally:
        session5.close()

    tool_execute_2 = AsyncMock(
        return_value={"result": "ok", "usage": {"tokens": 10, "cost_usd": 0.001}}
    )

    planner2 = MagicMock()
    planner2.plan = AsyncMock(return_value=plan)

    critic2 = MagicMock()
    critic2.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic2.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    session6 = TestSession()
    try:
        with UnitOfWork(session6) as uow:
            with patch(
                "saz.engine.executor.EventEmitter",
                side_effect=_make_committing_emitter(uow),
            ):
                executor = _build_executor(uow, planner2, critic2, tool_execute_2)
                asyncio.run(executor.execute_run(run_id))
    finally:
        session6.close()

    # After second retry: run completed, extract has 3 attempts
    session7 = TestSession()
    try:
        run = session7.query(Run).filter_by(id=run_id).one()
        assert run.status == "completed"

        extract_steps = (
            session7.query(Step)
            .filter_by(run_id=run_id, name="extract")
            .order_by(Step.attempt)
            .all()
        )
        assert len(extract_steps) == 3
        assert extract_steps[0].attempt == 1
        assert extract_steps[0].status == "failed"
        assert extract_steps[1].attempt == 2
        assert extract_steps[1].status == "failed"
        assert extract_steps[2].attempt == 3
        assert extract_steps[2].status == "completed"

        # Only one run should exist
        all_runs = session7.query(Run).filter_by(flow_id=flow_id).all()
        assert len(all_runs) == 1
    finally:
        session7.close()


# ---------------------------------------------------------------------------
# 8. Error summary uses latest attempt after retry, not stale historical one
# ---------------------------------------------------------------------------


def test_error_summary_uses_latest_attempt_after_retry(db_engine):
    """After retry that fails again, the error summary must reflect the
    latest attempt's error, not the original attempt-1 error.

    This is a regression test for the bug where:
        failed_step = next(s for s in run.steps if s.status == "failed")
    picked the earliest failed attempt (ordered by number, attempt) rather
    than the latest attempt of the failing step.
    """
    flow_id = "flow-errsummary"
    run_id = "run-errsummary"

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    try:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id=flow_id,
            name="test-errsummary",
            definition={
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": STEPS_DEF,
                },
                "policies": {"budget_usd": 1.0},
            },
        )
        # Run failed after retry — step "draft" has two failed attempts
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id=run_id,
            flow_id=flow_id,
            status="failed",
            planner_mode="deterministic",
            payload={"text": "hello"},
            error={"message": "step failed", "type": "ToolExecutionError"},
        )

        # Completed steps
        step_extract = Step(
            run_id=run_id,
            number=0,
            name="extract",
            step_type="ai.extract",
            status="completed",
            attempt=1,
            output={"result": "ok"},
        )
        step_validate = Step(
            run_id=run_id,
            number=1,
            name="validate",
            step_type="ai.extract",
            status="completed",
            attempt=1,
            output={"result": "ok"},
        )
        # draft attempt 1 — original failure (stale)
        step_draft_a1 = Step(
            run_id=run_id,
            number=2,
            name="draft",
            step_type="ai.extract",
            status="failed",
            attempt=1,
            error={"message": "original failure from attempt 1", "type": "OldError"},
        )
        # draft attempt 2 — latest failure (current)
        step_draft_a2 = Step(
            run_id=run_id,
            number=2,
            name="draft",
            step_type="ai.extract",
            status="failed",
            attempt=2,
            error={"message": "new failure from attempt 2", "type": "NewError"},
        )
        session.add_all([flow, run, step_extract, step_validate, step_draft_a1, step_draft_a2])
        session.commit()
    finally:
        session.close()

    # Simulate the logic used in get_run_detail to find the failed step
    session2 = TestSession()
    try:
        run = session2.query(Run).filter_by(id=run_id).one()
        # Force load steps ordered by (number, attempt)
        steps = sorted(run.steps, key=lambda s: (s.number, s.attempt))

        # Apply the corrected latest-attempt logic (mirrors the fix in runs.py)
        latest_by_name: dict[str, Step] = {}
        for s in steps:
            existing = latest_by_name.get(s.name)
            if existing is None or s.attempt > existing.attempt:
                latest_by_name[s.name] = s
        latest_steps = sorted(latest_by_name.values(), key=lambda s: s.number)
        failed_step = next((s for s in latest_steps if s.status == "failed"), None)

        assert failed_step is not None
        # Must be attempt 2 (the latest), not attempt 1 (the stale historical one)
        assert failed_step.attempt == 2, f"Expected latest attempt (2), got {failed_step.attempt}"
        assert failed_step.error["message"] == "new failure from attempt 2"

        # Also verify the enrichment service gets the right data
        error_summary = ErrorEnrichmentService.build_error_summary(run, failed_step)
        assert error_summary is not None
        assert "new failure from attempt 2" in error_summary.message
    finally:
        session2.close()


# ---------------------------------------------------------------------------
# 10. Error summary with mixed attempts: some completed, some failed
# ---------------------------------------------------------------------------


def test_error_summary_ignores_old_failed_attempts_of_now_completed_steps(db_engine):
    """If a step failed on attempt 1 but succeeded on attempt 2,
    the error summary must NOT pick it as the failed step.

    Scenario: extract failed (a1) → succeeded (a2), draft failed (a1).
    The error summary should point to draft, not extract.
    """
    flow_id = "flow-errsummary-mixed"
    run_id = "run-errsummary-mixed"

    TestSession = sessionmaker(bind=db_engine)
    session = TestSession()
    try:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id=flow_id,
            name="test-errsummary-mixed",
            definition={
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": STEPS_DEF,
                },
                "policies": {"budget_usd": 1.0},
            },
        )
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id=run_id,
            flow_id=flow_id,
            status="failed",
            planner_mode="deterministic",
            payload={"text": "hello"},
            error={"message": "step failed"},
        )

        # extract: failed on attempt 1, succeeded on attempt 2
        step_extract_a1 = Step(
            run_id=run_id,
            number=0,
            name="extract",
            step_type="ai.extract",
            status="failed",
            attempt=1,
            error={"message": "extract failed originally"},
        )
        step_extract_a2 = Step(
            run_id=run_id,
            number=0,
            name="extract",
            step_type="ai.extract",
            status="completed",
            attempt=2,
            output={"result": "ok"},
        )
        # validate: completed on attempt 1
        step_validate = Step(
            run_id=run_id,
            number=1,
            name="validate",
            step_type="ai.extract",
            status="completed",
            attempt=1,
            output={"result": "ok"},
        )
        # draft: failed on attempt 1 (current failure)
        step_draft = Step(
            run_id=run_id,
            number=2,
            name="draft",
            step_type="ai.extract",
            status="failed",
            attempt=1,
            error={"message": "draft failed"},
        )
        session.add_all(
            [
                flow,
                run,
                step_extract_a1,
                step_extract_a2,
                step_validate,
                step_draft,
            ]
        )
        session.commit()
    finally:
        session.close()

    session2 = TestSession()
    try:
        run = session2.query(Run).filter_by(id=run_id).one()
        steps = sorted(run.steps, key=lambda s: (s.number, s.attempt))

        # Apply latest-attempt filtering
        latest_by_name: dict[str, Step] = {}
        for s in steps:
            existing = latest_by_name.get(s.name)
            if existing is None or s.attempt > existing.attempt:
                latest_by_name[s.name] = s
        latest_steps = sorted(latest_by_name.values(), key=lambda s: s.number)
        failed_step = next((s for s in latest_steps if s.status == "failed"), None)

        # Should point to draft, not extract (extract succeeded on attempt 2)
        assert failed_step is not None
        assert failed_step.name == "draft"
        assert failed_step.error["message"] == "draft failed"

        # extract's latest attempt is completed — must not appear as failed
        extract_latest = latest_by_name["extract"]
        assert extract_latest.status == "completed"
        assert extract_latest.attempt == 2
    finally:
        session2.close()


# ---------------------------------------------------------------------------
# Cross-step $step('x').field templating must resolve
# ---------------------------------------------------------------------------
#
# Regression: the executor stored `context["step_results"][id] = step_result`
# (a flat dict) but TemplateContext._resolve_step_output reads
# `step_results[id]["output"]`. Every cross-step reference resolved to None,
# and downstream `artifact.store` calls handed the verifier a content blob
# with empty fields (e.g. dry_run.status = ""), which the post-execution
# critic correctly rejected. The fix wraps step results under "output" at
# every executor write site so the templating contract holds.


def test_cross_step_templating_resolves_through_executor(db_engine):
    flow_id = "flow-cross-step-template"
    run_id = "run-cross-step-template"

    TestSession = sessionmaker(bind=db_engine)
    with TestSession() as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id=flow_id,
            name="cross-step-template-flow",
            definition={
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {"id": "produce", "type": "ai.extract", "instruction": "produce"},
                        {
                            "id": "consume",
                            "type": "tool.call",
                            "tool": "echo_tool",
                            "input_template": {
                                # This is the bit that breaks if step_results
                                # isn't wrapped under "output".
                                "received_status": "{{ $step('produce').status }}",
                            },
                        },
                    ],
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
            payload={},
        )
        session.add_all([flow, run])
        session.commit()

    plan = _make_plan(
        [
            PlanStep(
                step_id="produce",
                step_type="ai.extract",
                reasoning="produce",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
                input_template={"instruction": "produce", "data": {}},
                tool_name="ai.extract",
            ),
            PlanStep(
                step_id="consume",
                step_type="tool.call",
                reasoning="consume",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
                input_template={"received_status": "{{ $step('produce').status }}"},
                tool_name="echo_tool",
            ),
        ]
    )
    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    # Tool returns from each step:
    #   produce → {"status": "ready", "kind": "demo"}
    #   consume → captures its inbound arguments so we can assert
    consume_calls: list[dict] = []

    async def tool_execute(tool_name, arguments, **_kwargs):
        if tool_name == "ai.extract":
            return {"status": "ready", "kind": "demo"}
        if tool_name == "echo_tool":
            consume_calls.append(dict(arguments))
            return {"echoed": True}
        raise AssertionError(f"unexpected tool {tool_name}")

    # Real ExecutorAgent so the template engine actually fires.
    real_executor_agent = ExecutorAgent()
    tool_registry = MagicMock(spec=ToolRegistry)
    tool_registry.get_tool_specs.return_value = []
    tool_registry.get_tool_specs_dict.return_value = {
        "ai.extract": {"name": "ai.extract", "input_schema": {"properties": {}}},
        "echo_tool": {"name": "echo_tool", "input_schema": {"properties": {}}},
    }
    tool_registry.execute_tool = AsyncMock(side_effect=tool_execute)

    session = TestSession()
    try:
        with UnitOfWork(session) as uow:
            with patch(
                "saz.engine.executor.EventEmitter",
                side_effect=_make_committing_emitter(uow),
            ):
                executor = WorkflowExecutor(
                    uow=uow,
                    tool_registry=tool_registry,
                    planner=planner,
                    executor_agent=real_executor_agent,
                    critic=critic,
                    policy_engine=PolicyEngine(),
                )
                asyncio.run(executor.execute_run(run_id))

        # The consume step's arguments must include the value resolved from
        # produce's output. If the executor regresses to storing step_results
        # as a flat dict, this comes back empty/None and the assertion fails.
        assert consume_calls, "consume step should have been invoked"
        assert consume_calls[0].get("received_status") == "ready", (
            "cross-step $step('produce').status must resolve to the real value, "
            f"got arguments={consume_calls[0]!r}"
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Same-run retry must work after a PolicyViolation block
# ---------------------------------------------------------------------------
#
# Regression: PolicyViolation (e.g. PII detected on a disallowed path of
# artifact.store) was leaving the current Step row in "running" status.
# StepRepository.get_first_failed_for_run filters to status='failed', so
# it returned None, and service.retry() raised "No failing step found".
# That blocked the retry button entirely for any policy-blocked run.


def test_policy_violation_marks_step_failed_so_retry_can_find_it(db_engine):
    flow_id = "flow-policy-retry"
    run_id = "run-policy-retry"

    # Build a single-step plan that the policy engine will block.
    TestSession = sessionmaker(bind=db_engine)
    with TestSession() as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id=flow_id,
            name="policy-retry-flow",
            definition={
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "store_record",
                            "type": "tool.call",
                            "tool": "artifact.store",
                            "input_template": {"content": {"requester": "alice@example.com"}},
                        }
                    ],
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
            payload={},
        )
        session.add_all([flow, run])
        session.commit()

    plan = _make_plan(
        [
            PlanStep(
                step_id="store_record",
                step_type="tool.call",
                reasoning="Audit record",
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
            )
        ]
    )

    planner = MagicMock()
    planner.plan = AsyncMock(return_value=plan)

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_make_critique(Verdict.PASS))
    critic.critique = AsyncMock(return_value=_make_critique(Verdict.PASS))

    tool_execute = AsyncMock(return_value={"result": "ok"})

    # Drive the failure by short-circuiting the real policy engine's
    # tool-call check. Using a real PolicyEngine keeps the rest of the
    # executor's policy plumbing happy (budget tracker, replan limit,
    # token vault) and avoids a brittle wall of MagicMock attributes.
    blocking_policy = PolicyEngine()
    blocking_policy.check_tool_call = MagicMock(  # type: ignore[method-assign]
        return_value=(False, "PII detected on non-approved paths: ['content.requester']")
    )

    session = TestSession()
    try:
        with UnitOfWork(session) as uow:
            with patch(
                "saz.engine.executor.EventEmitter",
                side_effect=_make_committing_emitter(uow),
            ):
                executor_agent = MagicMock(spec=ExecutorAgent)
                executor_agent.ground.return_value = ToolCall(
                    tool="artifact.store",
                    arguments={"content": {"requester": "alice@example.com"}},
                    idempotency_key="k",
                    rationale="audit",
                )
                tool_registry = MagicMock(spec=ToolRegistry)
                tool_registry.get_tool_specs.return_value = []
                tool_registry.get_tool_specs_dict.return_value = {}
                tool_registry.execute_tool = tool_execute
                executor = WorkflowExecutor(
                    uow=uow,
                    tool_registry=tool_registry,
                    planner=planner,
                    executor_agent=executor_agent,
                    critic=critic,
                    policy_engine=blocking_policy,
                )
                asyncio.run(executor.execute_run(run_id))

        # The tool was never executed — the policy short-circuited it.
        tool_execute.assert_not_called()

        # Run must be marked failed, AND the step row must be flipped to
        # "failed" (this is the actual regression — it used to stay "running").
        session2 = TestSession()
        try:
            run = session2.query(Run).filter_by(id=run_id).one()
            assert run.status == "failed"
            step = (
                session2.query(Step)
                .filter_by(run_id=run_id, name="store_record")
                .order_by(Step.attempt.desc())
                .first()
            )
            assert step is not None
            assert (
                step.status == "failed"
            ), f"PolicyViolation should mark the step row failed, got {step.status!r}"
            assert step.error is not None
            assert step.error.get("type") == "PolicyViolation"
        finally:
            session2.close()

        # And service.retry must be able to find the failed step — otherwise
        # the retry button is a dead end for any policy-blocked run.
        session3 = TestSession()
        try:
            with UnitOfWork(session3) as uow:
                RunService(uow).retry(run_id)
            run = session3.query(Run).filter_by(id=run_id).one()
            assert run.status == "queued"
        finally:
            session3.close()
    finally:
        session.close()
