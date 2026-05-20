"""artifact.store must persist an Artifact DB row, not just a filesystem JSON.

Bug being pinned: ArtifactTool.store() writes
``<artifact_storage_path>/<artifact_id>.json`` and returns the metadata, but
no code in saz/engine/executor.py ever calls uow.artifacts.create(). The
Artifact ORM model and ArtifactRepository exist; the read side reports
``run.artifacts`` via the Run.artifacts relationship; example workflows
declare artifact.store steps — yet the database side of that contract is
unwired.

This file pins the contract at the system level: after a successful
artifact.store step the run owns at least one DB-level Artifact row.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.orm import Session

from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import (
    Critique,
    ErrorHandling,
    ExecutionPlan,
    PlanStep,
    Verdict,
)
from saz.db.models import Artifact, Flow, Run
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.tools.artifact_tool import ArtifactTool
from saz.tools.registry import ToolRegistry
from tests.conftest import TEST_USER_ID


def _setup_flow_and_run(session: Session) -> tuple[str, str]:
    flow_id = "flow_artifact_persist"
    run_id = "run_artifact_persist_1"
    flow = Flow(
        created_by_user_id=TEST_USER_ID,
        id=flow_id,
        name="artifact_persist",
        definition={
            "schema_version": 1,
            "flow": {"name": "artifact_persist", "description": "test"},
            "workflow": {
                "planner_mode": "deterministic",
                "steps": [
                    {
                        "id": "store_report",
                        "type": "artifact.store",
                        "description": "Persist final report",
                        "params": {"name": "report", "content": {"x": 1}},
                    }
                ],
            },
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
    return flow_id, run_id


def _make_plan() -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        steps=[
            PlanStep(
                step_id="store_report",
                step_type="artifact.store",
                tool_name="artifact.store",
                input_template={"name": "report", "content": {"x": 1}},
                expected_output_schema={"type": "object"},
                error_handling=ErrorHandling.FAIL,
                max_retries=0,
                reasoning="store",
            )
        ],
        estimated_cost_usd=0.0,
        estimated_time_seconds=0,
        reasoning="single-step artifact test",
    )


def _pass_critique() -> Critique:
    return Critique(
        verdict=Verdict.PASS,
        reasoning="ok",
        issues=[],
        safety_flags=[],
        suggestions={},
        confidence=0.95,
    )


def test_artifact_store_creates_db_artifact_row(db_engine, tmp_path: Path):
    """Run a one-step artifact.store flow and assert a row exists in artifacts."""
    artifact_tool = ArtifactTool(storage_path=str(tmp_path / "artifacts"))
    tool_registry = ToolRegistry(artifact_tool=artifact_tool)

    planner = MagicMock()
    planner.plan = AsyncMock(return_value=_make_plan())

    critic = MagicMock()
    critic.verify_proposal = AsyncMock(return_value=_pass_critique())
    critic.critique = AsyncMock(return_value=_pass_critique())

    executor_agent = ExecutorAgent()

    with Session(db_engine) as session:
        flow_id, run_id = _setup_flow_and_run(session)

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            workflow_executor = WorkflowExecutor(
                uow=uow,
                tool_registry=tool_registry,
                planner=planner,
                critic=critic,
                executor_agent=executor_agent,
                policy_engine=PolicyEngine(),
            )
            try:
                asyncio.run(workflow_executor.execute_run(run_id))
            except Exception:
                # Even if the broader run unwinds for unrelated reasons, the
                # artifact.store step itself succeeds at the tool level — the
                # bug is that NO Artifact row is ever created during that
                # success. The assertion below is what matters.
                pass

    with Session(db_engine) as session:
        rows = session.query(Artifact).filter(Artifact.run_id == run_id).all()
        assert rows, (
            "After a successful artifact.store step the run must own at "
            "least one Artifact row. Today the tool writes a JSON file but "
            "the executor never calls uow.artifacts.create(), so run.artifacts "
            "is empty in the DB and any UI/report that reads it shows no "
            "artifacts despite the workflow having produced one."
        )
