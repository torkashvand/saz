"""Executor-level regression tests for the RFQ/RFP drafting workflow.

These run the real deterministic executor (real DeterministicPlanner, real
ExecutorAgent, real PolicyEngine) over the committed workflow definition with
fake AI-op tools, so the budget gate's actual blocking behaviour is exercised —
not just the compiled structure.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.db.models import Flow, Run, Step
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.tools.docx_tool import DocxRenderTool
from saz.tools.registry import ToolRegistry
from tests.conftest import TEST_USER_ID
from tests.fakes.critic import FakeCritic
from tests.fakes.tools import RecordingTool

_YAML = (
    Path(__file__).resolve().parents[2] / "saz" / "examples" / "unified" / "rfq_rfp_drafting.yaml"
)
_DEFINITION = yaml.safe_load(_YAML.read_text())

_AI_USAGE = {"tokens": 1, "cost_usd": 0.0}


def _base_payload() -> dict:
    return {
        "project_name": "HR Information System",
        "objective_input": "Find a cost-effective, modern HR system.",
        "scope_input": "A core HR system with optional modules.",
        "background_input": "GÉANT seeks to replace its existing HR Information System.",
        "technical_requirements": "SSO; EU/UK data residency; TLS 1.2+.",
        "criticality": "high",
        "num_users": 180,
        "data_sensitivity": "confidential",
        "estimated_value_eur": 30000,
        "contract_duration": "2 years",
        "pricing_model": "per_user",
        "budget_cap_licenses_eur": 20000,
        "budget_cap_implementation_eur": 10000,
        "sourcing_strategy": "Open EU competition",
        "gdpr_data_residency": "EU or UK",
        "security_requirements": "Encryption in transit and at rest.",
        "minimum_requirements": "1. SSO via OIDC/SAML2",
        "weight_qualitative_pct": 80,
        "weight_price_pct": 20,
        "q1_pct": 50,
        "q2_pct": 20,
        "q3_pct": 10,
        "reference_number": "T88815",
        "date_of_issue": "05/07/2024",
        "deadline_clarification": "15/07/2024",
        "deadline_response": "19/07/2024",
        "eval1_end": "02/08/2024",
        "eval2_end": "09/08/2024",
        "awarding_date": "15/08/2024",
        "commencement_date": "01/10/2024",
        "contact_name": "Badreddine Ajbar El Gueriri",
        "contact_role": "Buyer",
        "contact_phone": "+31 6 29003633",
        "contact_email": "badre.ajbar@geant.org",
        "consultation_required": False,
    }


def _registry() -> tuple[ToolRegistry, RecordingTool]:
    registry = ToolRegistry()
    registry.register_custom_tool(
        "ai.extract",
        {"name": "ai.extract", "description": "fake", "input_schema": {"type": "object"}},
        RecordingTool(
            "ai.extract",
            response={
                "output": {
                    "missing_fields": [],
                    "inconsistencies": [],
                    "high_level_requirements": ["SSO"],
                    "detailed_requirements": [],
                },
                "usage": _AI_USAGE,
            },
        ).execute,
    )
    registry.register_custom_tool(
        "ai.evaluate",
        {"name": "ai.evaluate", "description": "fake", "input_schema": {"type": "object"}},
        RecordingTool(
            "ai.evaluate",
            response={"output": {"pass": True, "issues": []}, "usage": _AI_USAGE},
        ).execute,
    )
    registry.register_custom_tool(
        "ai.generate",
        {"name": "ai.generate", "description": "fake", "input_schema": {"type": "object"}},
        RecordingTool(
            "ai.generate",
            response={
                "output": {"background": "b", "objective": "o", "scope": "s"},
                "usage": _AI_USAGE,
            },
        ).execute,
    )
    docx = RecordingTool("docx_render", response=DocxRenderTool().spec)
    registry.register_custom_tool("docx_render", docx.spec, docx.execute)
    return registry, docx


def _committing_emitter(uow):
    def factory(*args, **kwargs):
        emitter = MagicMock()

        async def commit_and_broadcast():
            uow.commit()

        emitter.commit_and_broadcast = AsyncMock(side_effect=commit_and_broadcast)
        return emitter

    return factory


def _run_workflow(db_engine, run_id: str, payload: dict) -> RecordingTool:
    flow_id = f"flow-{run_id}"
    with Session(db_engine) as session:
        session.add_all(
            [
                Flow(
                    created_by_user_id=TEST_USER_ID,
                    id=flow_id,
                    name="rfq",
                    definition=_DEFINITION,
                ),
                Run(
                    created_by_user_id=TEST_USER_ID,
                    id=run_id,
                    flow_id=flow_id,
                    status="queued",
                    planner_mode="deterministic",
                    payload=payload,
                ),
            ]
        )
        session.commit()

    registry, docx = _registry()
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            with patch("saz.engine.executor.EventEmitter", side_effect=_committing_emitter(uow)):
                executor = WorkflowExecutor(
                    uow=uow,
                    tool_registry=registry,
                    planner=DeterministicPlanner(),
                    executor_agent=ExecutorAgent(),
                    critic=FakeCritic(),  # type: ignore[arg-type]
                    policy_engine=PolicyEngine(),
                )
                asyncio.run(executor.execute_run(run_id))
    return docx


def _step_status(db_engine, run_id: str) -> dict[str, str]:
    with Session(db_engine) as session:
        steps = session.query(Step).filter_by(run_id=run_id).order_by(Step.number).all()
        return {s.name: s.status for s in steps}


def test_over_budget_gate_blocks_drafting_and_rendering(db_engine):
    run_id = "run-rfq-overbudget"
    payload = _base_payload()
    payload["budget_cap_licenses_eur"] = 99999  # exceeds the €20,000 cap

    docx = _run_workflow(db_engine, run_id, payload)

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run.status == "completed", "blocked run should complete, not suspend for approval"

    statuses = _step_status(db_engine, run_id)
    assert statuses["validate_inputs"] == "completed"
    assert statuses["gate_budget"] == "completed"
    # Everything after the failed gate is skipped — no drafting, no approval, no render.
    for sid in (
        "pont_check",
        "draft_narrative",
        "procurement_review",
        "render_draft",
        "render_final",
    ):
        assert statuses[sid] == "skipped", f"{sid} should be skipped when the gate fails"
    assert docx.call_count == 0, "docx_render must not run when the budget gate fails"


def test_valid_input_passes_gate_and_reaches_procurement_review(db_engine):
    run_id = "run-rfq-valid"

    docx = _run_workflow(db_engine, run_id, _base_payload())

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run.status == "suspended"
        assert run.error["type"] == "HumanApprovalRequired"
        assert run.error["step_id"] == "procurement_review"

    statuses = _step_status(db_engine, run_id)
    assert statuses["validate_inputs"] == "completed"
    assert statuses["pont_check"] == "completed"
    assert statuses["draft_narrative"] == "completed"
    assert statuses["procurement_review"] == "suspended"
    # Render only happens after approval, which has not occurred yet.
    assert "render_draft" not in statuses
    assert docx.call_count == 0
