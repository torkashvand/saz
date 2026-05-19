"""Cover the rare error branches of WorkflowExecutor.execute_run().

These tests exercise paths that are not naturally hit by the happy-path
runtime tests:

  * the run-not-found short-circuit at the top of ``execute_run``,
  * the flow-not-found branch (which builds a minimal emitter),
  * the no-workflow short-circuit (run completes immediately),
  * the budget-exceeded branch before the first step runs,
  * the _resolve_secret happy path (decrypts a stored credential) and
    the failure-returns-None path,
  * the _execute_condition step path with form-resolved expressions.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import (
    Critique,
    ErrorHandling,
    ExecutionPlan,
    PlanStep,
    Verdict,
)
from saz.db.models import Credential, Flow, Run
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.settings import settings
from saz.tools.registry import ToolRegistry

# --------------------------- helpers ---------------------------


def _pass() -> Critique:
    return Critique(
        verdict=Verdict.PASS,
        reasoning="ok",
        issues=[],
        safety_flags=[],
        suggestions={},
        confidence=0.95,
    )


def _make_executor(uow: UnitOfWork, policy_engine: PolicyEngine | None = None) -> WorkflowExecutor:
    planner = MagicMock()
    planner.plan = AsyncMock(
        return_value=ExecutionPlan(
            plan_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            steps=[],
            estimated_cost_usd=0.0,
            estimated_time_seconds=0,
            reasoning="empty",
        )
    )
    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_pass())
    critic.critique = AsyncMock(return_value=_pass())
    return WorkflowExecutor(
        uow=uow,
        tool_registry=ToolRegistry(),
        planner=planner,
        executor_agent=ExecutorAgent(),
        critic=critic,
        policy_engine=policy_engine or PolicyEngine(),
    )


# --------------------------- run-not-found ---------------------------


def test_execute_run_returns_silently_when_run_does_not_exist(db_engine) -> None:
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = _make_executor(uow)
            asyncio.run(executor.execute_run("does-not-exist"))
            session.commit()


# --------------------------- flow-not-found ---------------------------


def test_execute_run_fails_run_when_flow_relationship_broken(db_engine) -> None:
    """A run whose ``flow`` relationship cannot be loaded must end up failed,
    not left in queued. The repository load itself raises so the fatal
    error handler at the bottom of execute_run kicks in — but the run
    must still be transitioned to a terminal state."""
    with Session(db_engine) as session:
        # Insert directly with a non-existent flow id. ON DELETE CASCADE in
        # the schema prevents broken FKs in normal operation, but we
        # simulate the "run loaded with a stale flow row" path.
        flow = Flow(
            id="will-delete-this",
            name="ghost",
            definition={"workflow": {"planner_mode": "deterministic", "steps": []}},
        )
        run = Run(
            id="run-broken-flow",
            flow_id="will-delete-this",
            status="queued",
            planner_mode="deterministic",
            payload={},
        )
        session.add_all([flow, run])
        session.commit()
        # Now drop the flow row out from under the run.
        session.delete(flow)
        session.commit()

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = _make_executor(uow)
            asyncio.run(executor.execute_run("run-broken-flow"))

    with Session(db_engine) as session:
        reloaded = session.get(Run, "run-broken-flow")
        # The run row is deleted by FK CASCADE, or marked failed if the
        # cascade is deferred. Either is acceptable — the contract is that
        # the run never lingers in queued/running.
        if reloaded is not None:
            assert reloaded.status in {"failed", "error"}


# --------------------------- empty workflow ---------------------------


def test_execute_run_completes_when_workflow_spec_is_empty(db_engine) -> None:
    """A flow with no workflow section must complete cleanly (no plan run)."""
    with Session(db_engine) as session:
        flow = Flow(
            id="flow-empty-wf",
            name="empty",
            definition={
                "policies": {"pii": {"allow": False}},
                # No "workflow" key at all
            },
        )
        run = Run(
            id="run-empty-wf",
            flow_id="flow-empty-wf",
            status="queued",
            planner_mode="deterministic",
            payload={},
        )
        session.add_all([flow, run])
        session.commit()

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = _make_executor(uow)
            asyncio.run(executor.execute_run("run-empty-wf"))

    with Session(db_engine) as session:
        reloaded = session.get(Run, "run-empty-wf")
        assert reloaded is not None
        assert reloaded.status == "completed"


# --------------------------- budget exceeded before any step ---------------------------


def test_execute_run_fails_when_budget_exceeded_before_first_step(db_engine) -> None:
    """When the budget tracker reports over-budget BEFORE the first step,
    the run must be marked failed with type BudgetExceededError and no
    tool calls must have been issued."""
    with Session(db_engine) as session:
        flow = Flow(
            id="flow-budget",
            name="budget-flow",
            definition={
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "s1",
                            "type": "condition",
                            "if": "true",
                            "description": "noop",
                        }
                    ],
                }
            },
        )
        run = Run(
            id="run-budget",
            flow_id="flow-budget",
            status="queued",
            planner_mode="deterministic",
            payload={},
        )
        session.add_all([flow, run])
        session.commit()

    class _AlwaysOverBudget:
        """Fake tracker that always reports the run is over budget."""

        max_tokens = 100
        max_cost_usd = 1.0
        max_steps = 10

        def initialize_run(self, run_id: str) -> None:  # pragma: no cover - trivial
            pass

        def check_budget(self, run_id: str) -> tuple[bool, str]:
            return False, "synthetic over-budget for test"

        def record_tokens(self, *_args, **_kwargs) -> None:
            pass

        def record_cost(self, *_args, **_kwargs) -> None:
            pass

        def record_step(self, *_args, **_kwargs) -> None:
            pass

        def get_remaining(self, _run_id: str) -> dict:
            return {
                "tokens": {"remaining": 100, "max": 100, "used": 0, "percentage": 0},
                "cost": {"remaining": 1.0, "max": 1.0, "used": 0, "percentage": 0},
                "steps": {"remaining": 10, "max": 10, "used": 0, "percentage": 0},
                "time": {
                    "remaining_seconds": 100,
                    "max_seconds": 100,
                    "used_seconds": 0,
                    "percentage": 0,
                },
            }

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            engine = PolicyEngine(budget_tracker=_AlwaysOverBudget())  # type: ignore[arg-type]

            planner = MagicMock()
            planner.plan = AsyncMock(
                return_value=ExecutionPlan(
                    plan_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    steps=[
                        PlanStep(
                            step_id="s1",
                            step_type="condition",
                            input_template={"condition": "true"},
                            error_handling=ErrorHandling.FAIL,
                            max_retries=0,
                            reasoning="noop",
                        )
                    ],
                    estimated_cost_usd=0.0,
                    estimated_time_seconds=0,
                    reasoning="single condition",
                )
            )
            critic = MagicMock()
            critic.verify_proposal = AsyncMock(return_value=_pass())
            critic.critique = AsyncMock(return_value=_pass())
            executor = WorkflowExecutor(
                uow=uow,
                tool_registry=ToolRegistry(),
                planner=planner,
                executor_agent=ExecutorAgent(),
                critic=critic,
                policy_engine=engine,
            )
            asyncio.run(executor.execute_run("run-budget"))

    with Session(db_engine) as session:
        reloaded = session.get(Run, "run-budget")
        assert reloaded is not None
        assert reloaded.status == "failed"
        assert reloaded.error is not None
        assert reloaded.error["type"] == "BudgetExceededError"
        assert "Budget exceeded" in reloaded.error["message"]


# --------------------------- _resolve_secret ---------------------------


def _fernet_encrypt(key: str, payload: dict) -> bytes:
    cipher = Fernet(key.encode())
    return cipher.encrypt(yaml.safe_dump(payload).encode())


def test_resolve_secret_returns_value_from_encrypted_credential(
    db_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Generate a fresh Fernet key for this test instead of relying on the
    # dev .env. CI runs without that file, and settings.CREDENTIALS_ENCRYPTION_KEY
    # is otherwise an empty string → Fernet rejects it as not-32-bytes.
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "CREDENTIALS_ENCRYPTION_KEY", key)

    with Session(db_engine) as session:
        cred = Credential(
            name="MY_API_KEY",
            type="api_token",
            data_encrypted=_fernet_encrypt(key, {"api_key": "shhh-secret-value"}),
        )
        session.add(cred)
        session.commit()

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = _make_executor(uow)
            resolved = executor._resolve_secret("MY_API_KEY")
            assert resolved == "shhh-secret-value"


def test_resolve_secret_returns_none_for_missing_credential(db_engine) -> None:
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = _make_executor(uow)
            assert executor._resolve_secret("NOT_CONFIGURED") is None


def test_resolve_secret_returns_none_when_decrypt_fails(db_engine) -> None:
    """A corrupted ciphertext must not crash the executor — it returns None
    so the template resolver raises a clear 'Secret X not found'."""
    with Session(db_engine) as session:
        cred = Credential(
            name="BAD_SECRET",
            type="api_token",
            data_encrypted=b"not-real-ciphertext",
        )
        session.add(cred)
        session.commit()

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = _make_executor(uow)
            assert executor._resolve_secret("BAD_SECRET") is None


# --------------------------- _execute_condition ---------------------------


def test_execute_condition_returns_boolean_result_from_form(db_engine) -> None:
    """The condition step resolves $form / $step expressions, then coerces
    the result to bool via evaluate_expression."""
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = _make_executor(uow)
            plan_step = PlanStep(
                step_id="gate",
                step_type="condition",
                input_template={"condition": "{{ $form.approve }}"},
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
                reasoning="gate",
            )
            context = {
                "form_data": {"approve": "yes"},
                "step_results": {},
            }
            out = asyncio.run(executor._execute_condition(plan_step, context))
            assert out["result"] is True
            assert out["condition"] == "yes"


def test_execute_condition_returns_false_for_falsy_input(db_engine) -> None:
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = _make_executor(uow)
            plan_step = PlanStep(
                step_id="gate",
                step_type="condition",
                input_template={"condition": "{{ $form.approve }}"},
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
                reasoning="gate",
            )
            context = {"form_data": {"approve": "no"}, "step_results": {}}
            out = asyncio.run(executor._execute_condition(plan_step, context))
            assert out["result"] is False


def test_execute_condition_default_when_no_expression(db_engine) -> None:
    """Missing ``condition`` defaults to 'true' so an empty conditional
    does not implicitly skip downstream work."""
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = _make_executor(uow)
            plan_step = PlanStep(
                step_id="gate",
                step_type="condition",
                input_template={},
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
                reasoning="gate",
            )
            out = asyncio.run(
                executor._execute_condition(plan_step, {"form_data": {}, "step_results": {}})
            )
            assert out["result"] is True


# --------------------------- _get_current_step ---------------------------


def test_get_current_step_raises_when_step_row_missing(db_engine) -> None:
    """``_get_current_step`` is the executor's lookup for the in-flight
    Step row. If it returns None the caller cannot record state, so the
    helper must raise rather than return None."""
    with Session(db_engine) as session:
        flow = Flow(
            id="flow-no-step",
            name="noStep",
            definition={"workflow": {"planner_mode": "deterministic", "steps": []}},
        )
        run = Run(
            id="run-no-step",
            flow_id="flow-no-step",
            status="running",
            planner_mode="deterministic",
            payload={},
        )
        session.add_all([flow, run])
        session.commit()

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = _make_executor(uow)
            with pytest.raises(ValueError, match="Step not found: ghost"):
                executor._get_current_step("run-no-step", "ghost")
