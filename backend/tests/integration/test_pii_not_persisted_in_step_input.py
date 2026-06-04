"""Regression: raw PII must not be persisted into step.input.

The executor writes the grounded tool arguments to ``step.input`` so the UI
can show what was called. That column was scrubbed for SECRETS only, so under
``pii.allow: false`` raw PII (e.g. an email on an allow-listed outbound path)
landed in the DB and leaked through ``GET /runs/{id}``.

The persisted column must be PII-redacted while live execution still receives
the real value — only the stored copy changes.
"""

import asyncio

from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.db.models import Flow, Run, Step
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.tools.registry import ToolRegistry
from tests.conftest import TEST_USER_ID
from tests.fakes.critic import FakeCritic
from tests.fakes.tools import RecordingTool

PII_EMAIL = "alice.requester@example.com"

HTTP_SPEC = {
    "name": "http_request",
    "description": "Fake recorded HTTP",
    "inputSchema": {
        "type": "object",
        "properties": {
            "method": {"type": "string"},
            "url": {"type": "string"},
            "body": {"type": "object"},
        },
        "required": ["method", "url"],
    },
}


def _seed_pii_flow(db_engine):
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_pii_input",
            name="pii_input",
            definition={
                "schema_version": 1,
                "flow": {"name": "pii_input", "description": "PII persisted in input"},
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "notify",
                            "type": "tool.call",
                            "description": "Send a request carrying a requester email",
                            "tool": "http_request",
                            "params": {
                                "method": "POST",
                                "url": "https://api.example.com/notify",
                                "body": {"email": PII_EMAIL},
                            },
                        }
                    ],
                },
                "policies": {
                    "budget_usd": 1.0,
                    "pii": {
                        "allow": False,
                        # Opt the email path in so the outbound call is NOT
                        # blocked — this exercises the persist path, not the
                        # block path.
                        "exceptions": {"tools": {"http_request": ["body.email"]}},
                    },
                },
            },
        )
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_pii_input_1",
            flow_id="flow_pii_input",
            status="queued",
            planner_mode="deterministic",
            payload={},
        )
        session.add_all([flow, run])
        session.commit()
    return "run_pii_input_1"


def test_pii_absent_from_persisted_step_input_and_api(db_engine, app_client):
    run_id = _seed_pii_flow(db_engine)

    http = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    registry = ToolRegistry()
    registry.register_custom_tool("http_request", http.spec, http.execute)

    with Session(db_engine) as session, UnitOfWork(session) as uow:
        executor = WorkflowExecutor(
            uow=uow,
            tool_registry=registry,
            planner=DeterministicPlanner(),
            executor_agent=ExecutorAgent(),
            critic=FakeCritic(),  # type: ignore[arg-type]
            policy_engine=PolicyEngine(enforce_pii_redaction=True),
        )
        asyncio.run(executor.execute_run(run_id))

    # Live execution must still receive the REAL value.
    assert http.call_count == 1, "tool should have executed on the allow-listed path"
    sent = str(http.calls[0])
    assert PII_EMAIL in sent, "the tool must receive the real PII value at execution time"

    # The persisted column must NOT carry raw PII.
    with Session(db_engine) as session:
        step = session.query(Step).filter(Step.run_id == run_id).one()
        assert step.status == "completed", step.status
        assert PII_EMAIL not in str(
            step.input
        ), f"raw PII leaked into persisted step.input: {step.input!r}"

    # ...and it must not leak through the run-detail API (which returns
    # step.input verbatim).
    resp = app_client.get(f"/api/v1/runs/{run_id}")
    assert resp.status_code == 200, resp.text
    assert PII_EMAIL not in resp.text, "raw PII leaked through GET /runs/{id}"
