"""Regression: run_metadata.skipped_steps must reflect actually-skipped steps.

``calculate_run_metadata`` hardcoded ``skipped_steps: 0``, so a flow with a
false ``when`` guard reported zero skipped steps through ``GET /runs/{id}``
even though the step was recorded as ``skipped``.
"""

import asyncio

from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.db.models import Flow, Run, Step
from saz.db.unit_of_work import UnitOfWork
from saz.domain.error_enrichment import ErrorEnrichmentService
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


def _seed(db_engine):
    with Session(db_engine) as session:
        session.add(
            Flow(
                created_by_user_id=TEST_USER_ID,
                id="flow_skip_meta",
                name="flow_skip_meta",
                definition={
                    "schema_version": 1,
                    "flow": {"name": "skip_meta", "description": "guard"},
                    "workflow": {
                        "planner_mode": "deterministic",
                        "steps": [
                            {
                                "id": "guarded",
                                "type": "tool.call",
                                "tool": "notify",
                                "description": "notify only when flagged",
                                "params": {},
                                "when": "{{ $form.flagged }}",
                            }
                        ],
                    },
                },
            )
        )
        session.add(
            Run(
                created_by_user_id=TEST_USER_ID,
                id="run_skip_meta",
                flow_id="flow_skip_meta",
                status="queued",
                planner_mode="deterministic",
                payload={"flagged": False},
            )
        )
        session.commit()


def test_calculate_run_metadata_counts_skipped():
    """Unit: a skipped step is counted, not hardcoded to 0."""

    class _S:
        def __init__(self, status):
            self.status = status

    class _R:
        steps = [_S("completed"), _S("skipped"), _S("skipped"), _S("failed")]

    meta = ErrorEnrichmentService.calculate_run_metadata(_R())  # type: ignore[arg-type]
    assert meta["skipped_steps"] == 2
    assert meta["succeeded_steps"] == 1
    assert meta["failed_steps"] == 1


def test_skipped_step_surfaces_in_run_metadata_api(db_engine, app_client):
    _seed(db_engine)
    reg = ToolRegistry()
    notify = RecordingTool("notify", response={"ok": True}, spec=NOTIFY_SPEC)
    reg.register_custom_tool("notify", notify.spec, notify.execute)

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        executor = WorkflowExecutor(
            uow=uow,
            tool_registry=reg,
            planner=DeterministicPlanner(),
            executor_agent=ExecutorAgent(),
            critic=FakeCritic(),  # type: ignore[arg-type]
            policy_engine=PolicyEngine(),
        )
        asyncio.run(executor.execute_run("run_skip_meta"))

    with Session(db_engine) as session:
        step = session.query(Step).filter(Step.run_id == "run_skip_meta").one()
        assert step.status == "skipped"

    resp = app_client.get("/api/v1/runs/run_skip_meta")
    assert resp.status_code == 200, resp.text
    meta = resp.json()["run_metadata"]
    assert meta["skipped_steps"] == 1, meta
