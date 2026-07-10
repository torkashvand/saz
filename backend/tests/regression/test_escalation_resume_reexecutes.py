"""Approving a pre-execution escalation must actually execute the tool.

A verifier ESCALATE fires BEFORE the tool runs: the step suspends with no
side effects. If resume completes that step, the executor skips it forever —
the approval payload masquerades as tool output, downstream $step()
references resolve against it, and the operator believes an action happened
that never did. Approval of a pre-execution escalation must re-execute the
step; approval of a post-execution escalation (tool already ran) must NOT
re-execute it, or the side effect happens twice.
"""

import asyncio

from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import Verdict
from saz.db.models import Flow, Run, Step
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.services.run_service import RunService
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


def _seed_flow_and_run(session: Session, run_id: str, downstream_url: str) -> None:
    session.add(
        Flow(
            created_by_user_id=TEST_USER_ID,
            id=f"flow_{run_id}",
            name=f"flow_{run_id}",
            definition={
                "schema_version": 1,
                "flow": {"name": run_id, "description": "escalation resume"},
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "sensitive_step",
                            "type": "tool.call",
                            "description": "escalated by the verifier",
                            "tool": "http_request",
                            "params": {"method": "POST", "url": "https://api.example/sensitive"},
                        },
                        {
                            "id": "downstream",
                            "type": "tool.call",
                            "description": "depends on the escalated step",
                            "tool": "http_request",
                            "params": {"method": "GET", "url": downstream_url},
                        },
                    ],
                },
            },
        )
    )
    session.add(
        Run(
            created_by_user_id=TEST_USER_ID,
            id=run_id,
            flow_id=f"flow_{run_id}",
            status="queued",
            planner_mode="deterministic",
            payload={},
        )
    )
    session.commit()


def _execute_segment(db_engine, run_id: str, tool: RecordingTool, critic: FakeCritic) -> None:
    """One scheduler-style execution segment: fresh executor, fresh policy engine."""
    registry = ToolRegistry()
    registry.register_custom_tool("http_request", tool.spec, tool.execute)
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = WorkflowExecutor(
                uow=uow,
                tool_registry=registry,
                planner=DeterministicPlanner(),
                executor_agent=ExecutorAgent(),
                critic=critic,  # type: ignore[arg-type]
                policy_engine=PolicyEngine(),
            )
            asyncio.run(executor.execute_run(run_id))


def _resume(db_engine, run_id: str, resume_data: dict) -> None:
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            RunService(uow).resume_run(run_id, resume_data=resume_data)


def test_pre_execution_escalation_resume_reexecutes_tool(db_engine):
    """Approve a verifier escalation → the tool must run, downstream $step()
    must see the REAL tool output, and the run must complete."""
    run_id = "run_preexec_escalation"
    with Session(db_engine) as session:
        _seed_flow_and_run(
            session,
            run_id,
            downstream_url="https://api.example/notify/{{ $step('sensitive_step').ticket }}",
        )

    tool = RecordingTool("http_request", response={"ticket": "TCK-42"}, spec=HTTP_SPEC)
    # The verifier escalates sensitive_step on BOTH segments (a deterministic
    # verifier has no memory of the approval); downstream gets the PASS default.
    critic = FakeCritic(verify_verdicts=[Verdict.ESCALATE, Verdict.ESCALATE])

    # Segment 1: suspends before the tool runs.
    _execute_segment(db_engine, run_id, tool, critic)
    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.status == "suspended"
        assert run.error is not None
        assert run.error.get("type") == "EscalationRequired"
        assert run.error.get("pre_execution") is True
    assert tool.call_count == 0, "pre-execution escalation must not execute the tool"

    # Human approves.
    _resume(db_engine, run_id, resume_data={"approved": True, "approver": "ops"})

    # The approved-but-never-executed step must NOT be marked completed —
    # that would make the executor skip it forever.
    with Session(db_engine) as session:
        steps = session.query(Step).filter_by(run_id=run_id, name="sensitive_step").all()
        assert steps, "escalated step row must exist"
        assert all(s.status != "completed" for s in steps)

    # Segment 2: the recorded approval lets execution proceed even though the
    # verifier escalates again.
    _execute_segment(db_engine, run_id, tool, critic)

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.status == "completed", f"run should complete, got {run.status}: {run.error}"

        latest = max(
            session.query(Step).filter_by(run_id=run_id, name="sensitive_step").all(),
            key=lambda s: s.attempt,
        )
        assert latest.status == "completed"
        assert latest.output is not None and latest.output.get("ticket") == "TCK-42"

    sensitive_calls = [c for c in tool.calls if c.get("url") == "https://api.example/sensitive"]
    assert len(sensitive_calls) == 1, "approved step must execute exactly once"
    downstream_calls = [c for c in tool.calls if "notify" in c.get("url", "")]
    assert downstream_calls, "downstream step must run after re-execution"
    assert (
        downstream_calls[0]["url"] == "https://api.example/notify/TCK-42"
    ), "downstream must resolve the REAL tool output, not the approval payload"


def test_post_execution_escalation_resume_does_not_reexecute_tool(db_engine):
    """Approve a critic (post-execution) escalation → the tool already ran;
    resume must advance past the step WITHOUT running it a second time."""
    run_id = "run_postexec_escalation"
    with Session(db_engine) as session:
        _seed_flow_and_run(session, run_id, downstream_url="https://api.example/notify/static")

    tool = RecordingTool("http_request", response={"ticket": "TCK-42"}, spec=HTTP_SPEC)
    critic = FakeCritic(critique_verdicts=[Verdict.ESCALATE])

    # Segment 1: tool executes, then the critic escalates the result.
    _execute_segment(db_engine, run_id, tool, critic)
    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.status == "suspended"
        assert run.error is not None
        assert run.error.get("type") == "EscalationRequired"
        assert run.error.get("pre_execution") is False
    sensitive_calls = [c for c in tool.calls if c.get("url") == "https://api.example/sensitive"]
    assert len(sensitive_calls) == 1, "post-execution escalation happens AFTER the tool ran"

    _resume(db_engine, run_id, resume_data={"approved": True, "approver": "ops"})

    # Segment 2: step already executed — must be skipped, downstream runs.
    _execute_segment(db_engine, run_id, tool, critic)

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.status == "completed", f"run should complete, got {run.status}: {run.error}"

    sensitive_calls = [c for c in tool.calls if c.get("url") == "https://api.example/sensitive"]
    assert len(sensitive_calls) == 1, "side effect must not happen twice on resume"
    assert any("notify" in c.get("url", "") for c in tool.calls)
