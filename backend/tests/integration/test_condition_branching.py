"""A step's `when` guard provides real conditional branching.

A false guard skips the step: no tool runs, the step is recorded as skipped
(not completed), and a step.skipped event is emitted. A true guard runs the
step normally.
"""

import asyncio

from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.db.models import Event, Flow, Run, Step
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.tools.registry import ToolRegistry
from tests.conftest import TEST_USER_ID
from tests.fakes.critic import FakeCritic
from tests.fakes.tools import RecordingTool

NOTIFY_SPEC = {
    "name": "notify",
    "description": "fake",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


def _seed(db_engine, when_expr, payload):
    with Session(db_engine) as session:
        session.add(
            Flow(
                created_by_user_id=TEST_USER_ID,
                id="flow_when",
                name="flow_when",
                definition={
                    "schema_version": 1,
                    "flow": {"name": "when", "description": "guard"},
                    "workflow": {
                        "planner_mode": "deterministic",
                        "steps": [
                            {
                                "id": "guarded",
                                "type": "tool.call",
                                "tool": "notify",
                                "description": "notify only when flagged",
                                "params": {},
                                "when": when_expr,
                            }
                        ],
                    },
                },
            )
        )
        session.add(
            Run(
                created_by_user_id=TEST_USER_ID,
                id="run_when",
                flow_id="flow_when",
                status="queued",
                planner_mode="deterministic",
                payload=payload,
            )
        )
        session.commit()


def _run(db_engine, reg):
    with Session(db_engine) as session, UnitOfWork(session) as uow:
        executor = WorkflowExecutor(
            uow=uow,
            tool_registry=reg,
            planner=DeterministicPlanner(),
            executor_agent=ExecutorAgent(),
            critic=FakeCritic(),  # type: ignore[arg-type]
            policy_engine=PolicyEngine(),
        )
        asyncio.run(executor.execute_run("run_when"))


def test_false_guard_skips_step(db_engine):
    _seed(db_engine, "{{ $form.flagged }}", payload={"flagged": False})
    reg = ToolRegistry()
    notify = RecordingTool("notify", response={"ok": True}, spec=NOTIFY_SPEC)
    reg.register_custom_tool("notify", notify.spec, notify.execute)

    _run(db_engine, reg)

    assert notify.call_count == 0, "guarded tool must not execute when guard is false"
    with Session(db_engine) as session:
        run = session.get(Run, "run_when")
        assert run.status == "completed"
        step = session.query(Step).filter(Step.run_id == "run_when", Step.name == "guarded").one()
        assert step.status == "skipped"
        types = [
            e.event_type for e in session.query(Event).filter(Event.run_id == "run_when").all()
        ]
        assert "step.skipped" in types, types


def test_true_guard_runs_step(db_engine):
    _seed(db_engine, "{{ $form.flagged }}", payload={"flagged": True})
    reg = ToolRegistry()
    notify = RecordingTool("notify", response={"ok": True}, spec=NOTIFY_SPEC)
    reg.register_custom_tool("notify", notify.spec, notify.execute)

    _run(db_engine, reg)

    assert notify.call_count == 1, "guarded tool must execute when guard is true"
    with Session(db_engine) as session:
        step = session.query(Step).filter(Step.run_id == "run_when", Step.name == "guarded").one()
        assert step.status == "completed"
