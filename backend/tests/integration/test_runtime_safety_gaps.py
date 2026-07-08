"""Regression coverage for runtime-safety hardening.

Covers three fixes that close gaps between Saz's safety claims and its
runtime behavior:

  * Phase 1 — an agentic workflow that declares no tools may NOT ground any
    tool (fail closed instead of falling back to the full registry).
  * Phase 2 — PII is redacted before it reaches the planner / verifier /
    critic LLM prompt surfaces.
  * Phase 3 — budget is checked BEFORE the first agentic planning LLM call.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.orm import Session

from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import ErrorHandling, ExecutionPlan, PlanStep
from saz.db.models import Event, Flow, Run
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.tools.registry import ToolRegistry
from tests.conftest import TEST_USER_ID
from tests.fakes.critic import FakeCritic
from tests.fakes.tools import RecordingTool

HTTP_SPEC = {
    "name": "http_request",
    "description": "fake",
    "input_schema": {
        "type": "object",
        "properties": {"method": {"type": "string"}, "url": {"type": "string"}},
        "required": ["method", "url"],
    },
}
AI_EXTRACT_SPEC = {
    "name": "ai.extract",
    "description": "fake model tool",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


def _seed_flow(db_engine, definition, *, planner_mode, payload=None):
    with Session(db_engine) as session:
        session.add_all(
            [
                Flow(
                    created_by_user_id=TEST_USER_ID,
                    id="flow_rs",
                    name="flow_rs",
                    definition=definition,
                ),
                Run(
                    created_by_user_id=TEST_USER_ID,
                    id="run_rs",
                    flow_id="flow_rs",
                    status="queued",
                    planner_mode=planner_mode,
                    payload=payload or {},
                ),
            ]
        )
        session.commit()


def _http_plan():
    planner = MagicMock()
    planner.plan = AsyncMock(
        return_value=ExecutionPlan(
            plan_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            steps=[
                PlanStep(
                    step_id="s1",
                    step_type="tool.call",
                    tool_name="http_request",
                    input_template={"method": "GET", "url": "https://api.example.com/x"},
                    reasoning="probe",
                )
            ],
            estimated_cost_usd=0.0,
            estimated_time_seconds=0,
            reasoning="probe",
        )
    )
    return planner


# --- Phase 1: agentic deny-all when no tools declared -------------------------


def test_agentic_no_declared_tools_denies_all(db_engine):
    """Agentic workflow with empty steps and no allowed_tools cannot ground
    a registered tool — the deterministic gate fails closed."""
    _seed_flow(
        db_engine,
        {
            "schema_version": 1,
            "flow": {"name": "rs", "description": "no tools"},
            "workflow": {"planner_mode": "agentic", "steps": []},
            "policies": {"budget_usd": 5.0},
        },
        planner_mode="agentic",
    )
    reg = ToolRegistry()
    http = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    reg.register_custom_tool("http_request", http.spec, http.execute)

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        executor = WorkflowExecutor(
            uow=uow,
            tool_registry=reg,
            planner=_http_plan(),
            executor_agent=ExecutorAgent(),
            critic=FakeCritic(),  # type: ignore[arg-type]
            policy_engine=PolicyEngine(),
        )
        try:
            asyncio.run(executor.execute_run("run_rs"))
        except Exception:
            pass

    assert http.call_count == 0, "undeclared tool must not execute"
    with Session(db_engine) as session:
        run = session.get(Run, "run_rs")
        assert run.status in ("failed", "error")
        types = [e.event_type for e in session.query(Event).filter(Event.run_id == "run_rs").all()]
        assert "policy.blocked" in types, types


# --- Phase 3: budget gate before planning ------------------------------------


def test_zero_budget_blocks_before_planning(db_engine):
    """An agentic run with a zero budget must fail before the planner LLM is
    ever called."""
    _seed_flow(
        db_engine,
        {
            "schema_version": 1,
            "flow": {"name": "rs", "description": "zero budget"},
            "workflow": {"planner_mode": "agentic", "steps": [], "allowed_tools": ["http_request"]},
            "policies": {"budget_usd": 0.0},
        },
        planner_mode="agentic",
    )
    reg = ToolRegistry()
    http = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    reg.register_custom_tool("http_request", http.spec, http.execute)
    planner = _http_plan()

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        executor = WorkflowExecutor(
            uow=uow,
            tool_registry=reg,
            planner=planner,
            executor_agent=ExecutorAgent(),
            critic=FakeCritic(),  # type: ignore[arg-type]
            policy_engine=PolicyEngine(),
        )
        asyncio.run(executor.execute_run("run_rs"))

    planner.plan.assert_not_called()
    assert http.call_count == 0
    with Session(db_engine) as session:
        run = session.get(Run, "run_rs")
        assert run.status == "failed"
        assert run.error and run.error.get("type") == "BudgetExceededError"
        types = [e.event_type for e in session.query(Event).filter(Event.run_id == "run_rs").all()]
        assert "policy.budget.exhausted" in types, types


# --- Phase 2: PII redacted before reaching model prompt surfaces -------------


def test_planner_receives_redacted_payload(db_engine):
    """The agentic planner must not receive raw PII from the run payload."""
    _seed_flow(
        db_engine,
        {
            "schema_version": 1,
            "flow": {"name": "rs", "description": "pii payload"},
            "workflow": {"planner_mode": "agentic", "steps": [], "allowed_tools": ["http_request"]},
            "policies": {"budget_usd": 5.0, "pii": {"allow": False}},
        },
        planner_mode="agentic",
        payload={"requester_email": "alice@example.com", "ticket": "INC-42"},
    )
    reg = ToolRegistry()
    planner = MagicMock()
    planner.plan = AsyncMock(
        return_value=ExecutionPlan(
            plan_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            steps=[],
            estimated_cost_usd=0.0,
            estimated_time_seconds=0,
            reasoning="noop",
        )
    )

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        executor = WorkflowExecutor(
            uow=uow,
            tool_registry=reg,
            planner=planner,
            executor_agent=ExecutorAgent(),
            critic=FakeCritic(),  # type: ignore[arg-type]
            policy_engine=PolicyEngine(),
        )
        asyncio.run(executor.execute_run("run_rs"))

    planner.plan.assert_called_once()
    current_data = planner.plan.call_args.kwargs["current_data"]
    assert "alice@example.com" not in str(current_data), current_data
    # Non-PII data is preserved for reasoning.
    assert "INC-42" in str(current_data)


def test_verifier_and_critic_receive_redacted_pii(db_engine):
    """A model-tool step's arguments must reach the verifier/critic with PII
    redacted (model tools are not blocked on PII, so this is the leak path)."""
    _seed_flow(
        db_engine,
        {
            "schema_version": 1,
            "flow": {"name": "rs", "description": "pii model tool"},
            "workflow": {
                "planner_mode": "deterministic",
                "steps": [
                    {
                        "id": "extract",
                        "type": "ai.extract",
                        "instruction": "extract fields",
                        "params": {"data": {"email": "bob@example.com"}},
                    }
                ],
            },
            "policies": {"pii": {"allow": False}},
        },
        planner_mode="deterministic",
    )
    reg = ToolRegistry()
    ai_tool = RecordingTool("ai.extract", response={"fields": {}}, spec=AI_EXTRACT_SPEC)
    reg.register_custom_tool("ai.extract", ai_tool.spec, ai_tool.execute)
    critic = FakeCritic()

    from saz.agents.deterministic_planner import DeterministicPlanner

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        executor = WorkflowExecutor(
            uow=uow,
            tool_registry=reg,
            planner=DeterministicPlanner(),
            executor_agent=ExecutorAgent(),
            critic=critic,  # type: ignore[arg-type]
            policy_engine=PolicyEngine(),
        )
        asyncio.run(executor.execute_run("run_rs"))

    assert critic.verify_calls, "verifier should have been called"
    verify_args = str(critic.verify_calls[0]["proposed_tool_call"])
    assert "bob@example.com" not in verify_args, verify_args
    assert critic.critique_calls, "critic should have been called"
    critique_args = str(critic.critique_calls[0]["tool_call"])
    assert "bob@example.com" not in critique_args, critique_args


# --- Phase 13: PII tokenization emits an auditable event ---------------------


def test_pii_tokenization_emits_audit_event(db_engine):
    """Tokenizing PII for a model tool emits policy.pii.redacted with no raw
    PII in the event payload."""
    from saz.agents.deterministic_planner import DeterministicPlanner

    _seed_flow(
        db_engine,
        {
            "schema_version": 1,
            "flow": {"name": "rs", "description": "pii audit"},
            "workflow": {
                "planner_mode": "deterministic",
                "steps": [
                    {
                        "id": "extract",
                        "type": "ai.extract",
                        "instruction": "extract",
                        "params": {"data": {"email": "carol@example.com"}},
                    }
                ],
            },
            "policies": {"pii": {"allow": False}},
        },
        planner_mode="deterministic",
    )
    reg = ToolRegistry()
    ai_tool = RecordingTool("ai.extract", response={"fields": {}}, spec=AI_EXTRACT_SPEC)
    reg.register_custom_tool("ai.extract", ai_tool.spec, ai_tool.execute)

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        executor = WorkflowExecutor(
            uow=uow,
            tool_registry=reg,
            planner=DeterministicPlanner(),
            executor_agent=ExecutorAgent(),
            critic=FakeCritic(),  # type: ignore[arg-type]
            policy_engine=PolicyEngine(),
        )
        asyncio.run(executor.execute_run("run_rs"))

    with Session(db_engine) as session:
        events = [
            e
            for e in session.query(Event).filter(Event.run_id == "run_rs").all()
            if e.event_type == "policy.pii.redacted"
        ]
        assert events, "policy.pii.redacted must be emitted when PII is tokenized"
        assert "carol@example.com" not in str(events[0].payload), events[0].payload


# --- Phase 15: ESCALATE-on-failure produces a resumable suspension -----------


def test_escalate_on_failure_is_resumable(db_engine):
    """A step with error_handling=ESCALATE that fails must suspend the run with
    a callback_id, a timeout, and a run.suspended event — not an unresumable,
    un-reapable suspended state."""
    _seed_flow(
        db_engine,
        {
            "schema_version": 1,
            "flow": {"name": "rs", "description": "escalate"},
            "workflow": {"planner_mode": "agentic", "steps": [], "allowed_tools": ["failing"]},
            "policies": {"budget_usd": 5.0},
        },
        planner_mode="agentic",
    )
    reg = ToolRegistry()
    failing = RecordingTool(
        "failing",
        raises=RuntimeError("boom"),
        spec={
            "name": "failing",
            "description": "always fails",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
    )
    reg.register_custom_tool("failing", failing.spec, failing.execute)

    planner = MagicMock()
    planner.plan = AsyncMock(
        return_value=ExecutionPlan(
            plan_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            steps=[
                PlanStep(
                    step_id="s1",
                    step_type="tool.call",
                    tool_name="failing",
                    error_handling=ErrorHandling.ESCALATE,
                    max_retries=0,
                    reasoning="risky",
                )
            ],
            estimated_cost_usd=0.0,
            estimated_time_seconds=0,
            reasoning="risky",
        )
    )

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        executor = WorkflowExecutor(
            uow=uow,
            tool_registry=reg,
            planner=planner,
            executor_agent=ExecutorAgent(),
            critic=FakeCritic(),  # type: ignore[arg-type]
            policy_engine=PolicyEngine(),
        )
        asyncio.run(executor.execute_run("run_rs"))

    with Session(db_engine) as session:
        run = session.get(Run, "run_rs")
        assert run.status == "suspended"
        # Resumable: a callback_id is present. Reapable: timeout_at is set.
        assert run.error.get("callback_id"), run.error
        assert run.error.get("timeout_at"), run.error
        types = [e.event_type for e in session.query(Event).filter(Event.run_id == "run_rs").all()]
        assert "run.suspended" in types, types


# --- Phase 4: human.approval metadata is surfaced, not silently dropped ------


def test_human_approval_metadata_surfaced(db_engine):
    """title/message/payload/approvers must appear in the approval event and
    the suspension payload instead of being parsed-then-ignored."""
    from saz.agents.deterministic_planner import DeterministicPlanner

    _seed_flow(
        db_engine,
        {
            "schema_version": 1,
            "flow": {"name": "rs", "description": "approval meta"},
            "workflow": {
                "planner_mode": "deterministic",
                "steps": [
                    {
                        "id": "approve",
                        "type": "human.approval",
                        "description": "approve the change",
                        "params": {
                            "title": "Approve deployment",
                            "message": "Please review the change",
                            "payload": {"change_id": "CHG-9"},
                            "approvers": ["alice"],
                            "approver_role": "release-manager",
                        },
                    }
                ],
            },
        },
        planner_mode="deterministic",
    )

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        executor = WorkflowExecutor(
            uow=uow,
            tool_registry=ToolRegistry(),
            planner=DeterministicPlanner(),
            executor_agent=ExecutorAgent(),
            critic=FakeCritic(),  # type: ignore[arg-type]
            policy_engine=PolicyEngine(),
        )
        asyncio.run(executor.execute_run("run_rs"))

    with Session(db_engine) as session:
        run = session.get(Run, "run_rs")
        assert run.status == "suspended"
        approval = run.error["approval"]
        assert approval["title"] == "Approve deployment"
        assert approval["message"] == "Please review the change"
        assert approval["payload"] == {"change_id": "CHG-9"}
        assert approval["approvers"] == ["alice"]
        assert approval["approver_role"] == "release-manager"

        approval_events = [
            e
            for e in session.query(Event).filter(Event.run_id == "run_rs").all()
            if e.event_type == "approval.requested"
        ]
        assert approval_events, "approval.requested event must be emitted"
        payload = approval_events[0].payload
        assert payload["title"] == "Approve deployment"
        assert payload["approvers"] == ["alice"]
