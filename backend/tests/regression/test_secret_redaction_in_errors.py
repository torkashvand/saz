"""Resolved $secret() values must never leak through failure paths.

The success path scrubs secrets from ``step.output``; the failure paths must
scrub them from ``Step.error``, ``Run.error``, and every emitted event too.
A realistic leak vector: a secret templated into a URL query string ends up
in the exception message when the HTTP call fails (HttpTool embeds the full
URL in ``HTTPStatusError``).
"""

import asyncio
import json
from typing import Any

import pytest
import yaml
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.db.models import Credential, Event, Flow, Run, Step
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.settings import settings
from saz.tools.registry import ToolRegistry
from tests.conftest import TEST_USER_ID
from tests.fakes.critic import FakeCritic

SECRET_VALUE = "tok-super-secret-12345"

HTTP_SPEC = {
    "name": "http_request",
    "description": "fake http tool",
    "input_schema": {
        "type": "object",
        "properties": {"method": {"type": "string"}, "url": {"type": "string"}},
        "required": ["method", "url"],
    },
}


class UrlEchoingFailureTool:
    """Mimics HttpTool: raises with the full (secret-bearing) URL in the message."""

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        raise Exception(f"HTTP 401 for GET {kwargs.get('url')}")


def _fernet_encrypt(key: str, payload: dict) -> bytes:
    return Fernet(key.encode()).encrypt(yaml.safe_dump(payload).encode())


def _seed(session: Session, run_id: str) -> None:
    session.add_all(
        [
            Flow(
                created_by_user_id=TEST_USER_ID,
                id=f"flow_{run_id}",
                name=f"flow_{run_id}",
                definition={
                    "schema_version": 1,
                    "flow": {"name": run_id, "description": "secret redaction"},
                    "workflow": {
                        "planner_mode": "deterministic",
                        "steps": [
                            {
                                "id": "call_api",
                                "type": "tool.call",
                                "description": "call an API with a secret in the URL",
                                "tool": "http_request",
                                "params": {
                                    "method": "GET",
                                    "url": "https://api.example/?key={{ $secret('ERP_TOKEN') }}",
                                },
                            }
                        ],
                    },
                    "policies": {"budget_usd": 5.0},
                },
            ),
            Run(
                created_by_user_id=TEST_USER_ID,
                id=run_id,
                flow_id=f"flow_{run_id}",
                status="queued",
                planner_mode="deterministic",
                payload={},
            ),
        ]
    )
    session.commit()


def _run(db_engine, run_id: str) -> None:
    registry = ToolRegistry()
    tool = UrlEchoingFailureTool()
    registry.register_custom_tool("http_request", HTTP_SPEC, tool.execute)
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
            try:
                asyncio.run(executor.execute_run(run_id))
            except Exception:
                pass


def test_secret_absent_from_step_error_run_error_and_events(
    db_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "CREDENTIALS_ENCRYPTION_KEY", key)

    run_id = "run_secret_err"
    with Session(db_engine) as session:
        session.add(
            Credential(
                created_by_user_id=TEST_USER_ID,
                name="ERP_TOKEN",
                type="api_token",
                data_encrypted=_fernet_encrypt(key, {"token": SECRET_VALUE}),
            )
        )
        _seed(session, run_id)

    _run(db_engine, run_id)

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.error is not None
        assert SECRET_VALUE not in json.dumps(run.error)
        # The message survives redaction (structure preserved, value scrubbed).
        assert "HTTP 401" in run.error["message"]
        assert "***REDACTED***" in run.error["message"]

        step = session.query(Step).filter(Step.run_id == run_id).first()
        assert step is not None
        assert step.status == "failed"
        assert step.error is not None
        assert SECRET_VALUE not in json.dumps(step.error)
        assert "***REDACTED***" in step.error["message"]

        events = session.query(Event).filter(Event.run_id == run_id).all()
        assert events, "run must emit events"
        for event in events:
            blob = json.dumps({"summary": event.summary, "payload": event.payload})
            assert SECRET_VALUE not in blob, f"secret leaked in event {event.event_type}"
