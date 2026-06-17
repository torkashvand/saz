"""Integration: human.approval gates auto-generate an approval brief.

Drives a real ``WorkflowExecutor`` to a human.approval gate and asserts the
suspended step carries an ``approval_brief`` without altering the plan, step
numbering, run/resume semantics, or audit events.
"""

import asyncio
import json

from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.agents.llm_port import LLMPort, LLMResponse, set_llm_port
from saz.db.models import Event, Flow, Run, Step
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.tools.registry import ToolRegistry
from tests.conftest import TEST_USER_ID, MockLLMPort
from tests.fakes.critic import FakeCritic
from tests.fakes.tools import RecordingTool

VALID_BRIEF = json.dumps(
    {
        "decision_title": "Approve continuing this procurement run?",
        "readiness": "ready",
        "readiness_label": "Ready for approval",
        "main_reason": "The pre-check passed; ready for human sign-off.",
        "critical_issues": [],
        "passed_checks": ["No missing fields"],
        "key_facts": [{"label": "Project", "value": "HR System"}],
        "approval_consequence": "If approved, Saz will continue with finalize.",
    }
)

TOOL_SPEC = {
    "name": "noop",
    "description": "Fake recorded tool",
    "inputSchema": {"type": "object", "properties": {}},
}


class _RaisingLLM(LLMPort):
    async def complete(self, *args, **kwargs) -> LLMResponse:  # type: ignore[override]
        raise RuntimeError("llm down")


def _make_flow(session: Session, *, opt_out: bool = False) -> str:
    approve_params: dict[str, object] = {"message": "Review the change before continuing."}
    if opt_out:
        approve_params["approval_brief"] = False
    flow = Flow(
        created_by_user_id=TEST_USER_ID,
        id="flow_brief_1",
        name="brief_flow",
        definition={
            "schema_version": 1,
            "flow": {"name": "brief_flow", "description": "approval brief gate"},
            "workflow": {
                "planner_mode": "deterministic",
                "steps": [
                    {"id": "precheck", "type": "tool.call", "tool": "precheck_tool"},
                    {
                        "id": "approve",
                        "type": "human.approval",
                        "description": "Sign-off",
                        "params": approve_params,
                    },
                    {"id": "finalize", "type": "tool.call", "tool": "finalize_tool"},
                ],
            },
            "policies": {"budget_usd": 1.0},
        },
    )
    run = Run(
        created_by_user_id=TEST_USER_ID,
        id="run_brief_1",
        flow_id="flow_brief_1",
        status="queued",
        planner_mode="deterministic",
        payload={"project_name": "HR System", "criticality": "high"},
    )
    session.add_all([flow, run])
    session.commit()
    return "run_brief_1"


def _registry() -> tuple[ToolRegistry, RecordingTool]:
    precheck = RecordingTool("precheck_tool", response={"missing_fields": []}, spec=TOOL_SPEC)
    finalize = RecordingTool("finalize_tool", response={"ok": True}, spec=TOOL_SPEC)
    registry = ToolRegistry()
    registry.register_custom_tool("precheck_tool", precheck.spec, precheck.execute)
    registry.register_custom_tool("finalize_tool", finalize.spec, finalize.execute)
    return registry, finalize


def _run_executor(db_engine, registry: ToolRegistry, run_id: str) -> None:
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = WorkflowExecutor(
                uow=uow,
                tool_registry=registry,
                planner=DeterministicPlanner(),
                executor_agent=ExecutorAgent(),
                critic=FakeCritic(),  # type: ignore[arg-type]
                policy_engine=PolicyEngine(),
            )
            asyncio.run(executor.execute_run(run_id))


def test_approval_gate_generates_brief_and_preserves_semantics(db_engine, app_client):
    set_llm_port(MockLLMPort([VALID_BRIEF]))
    with Session(db_engine) as session:
        run_id = _make_flow(session)

    registry, finalize = _registry()
    _run_executor(db_engine, registry, run_id)

    # The gate stopped the executor before the post-approval step.
    assert finalize.call_count == 0

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run.status == "suspended"

        steps = session.query(Step).filter(Step.run_id == run_id).order_by(Step.number).all()
        # No hidden/injected step: only the declared steps reached so far.
        assert [s.name for s in steps] == ["precheck", "approve"]
        assert [s.number for s in steps] == [0, 1]

        approve = next(s for s in steps if s.name == "approve")
        assert approve.status == "suspended"

        brief = (approve.input or {}).get("approval_brief")
        assert brief is not None, "approval step must carry approval_brief on its input"
        assert brief["generation_status"] == "generated"
        assert brief["decision_title"]
        assert brief["readiness_label"]
        assert "precheck" in brief["source_step_ids"]
        assert "finalize" in brief["approval_consequence"]

        # Audit semantics: approval requested + run suspended, but the approval
        # step is NOT completed at suspension time.
        events = session.query(Event).filter(Event.run_id == run_id).all()
        types = {e.event_type for e in events}
        assert "approval.requested" in types
        assert "run.suspended" in types
        completed_for_approve = [
            e for e in events if e.event_type == "step.completed" and e.step_id == approve.id
        ]
        assert completed_for_approve == []

    # Resume semantics still work: approve completes, finalize runs.
    from saz.services.run_service import RunService

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            RunService(uow).resume_run(run_id, resume_data={"approved": True})

    _run_executor(db_engine, registry, run_id)

    assert finalize.call_count >= 1
    with Session(db_engine) as session:
        steps = session.query(Step).filter(Step.run_id == run_id).all()
        # All three declared steps exist after resume; no extra hidden step.
        assert {s.name for s in steps} == {"precheck", "approve", "finalize"}
        approve = next(s for s in steps if s.name == "approve")
        finalize_step = next(s for s in steps if s.name == "finalize")
        assert approve.status == "completed"
        assert approve.output and approve.output.get("approved") is True
        assert finalize_step.status == "completed"
        # The brief persists on the step input through resume.
        assert (approve.input or {}).get("approval_brief", {}).get(
            "generation_status"
        ) == "generated"


def test_approval_gate_falls_back_when_llm_fails(db_engine, app_client):
    set_llm_port(_RaisingLLM())
    with Session(db_engine) as session:
        run_id = _make_flow(session)

    registry, finalize = _registry()
    _run_executor(db_engine, registry, run_id)

    # Failure does not break the gate.
    assert finalize.call_count == 0
    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run.status == "suspended"
        approve = next(
            s
            for s in session.query(Step).filter(Step.run_id == run_id).all()
            if s.name == "approve"
        )
        assert approve.status == "suspended"
        brief = (approve.input or {}).get("approval_brief")
        assert brief is not None
        assert brief["generation_status"] == "fallback"
        assert brief["warnings"]


def test_step_level_opt_out_skips_brief(db_engine, app_client):
    set_llm_port(MockLLMPort([VALID_BRIEF]))
    with Session(db_engine) as session:
        run_id = _make_flow(session, opt_out=True)

    registry, _finalize = _registry()
    _run_executor(db_engine, registry, run_id)

    with Session(db_engine) as session:
        approve = next(
            s
            for s in session.query(Step).filter(Step.run_id == run_id).all()
            if s.name == "approve"
        )
        assert approve.status == "suspended"
        assert "approval_brief" not in (approve.input or {})
