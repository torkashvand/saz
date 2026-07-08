"""Acceptance: resolved secrets must never reach the verifier/critic LLM.

Secrets resolved via ``$secret(...)`` are baked into grounded tool arguments
for *execution only*. The pre-execution verifier and post-execution critic
send the proposed tool call to an LLM provider, so those payloads must be
redacted first — both by sensitive key name and by known secret value.
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
from saz.agents.schemas import Critique, Verdict
from saz.db.models import Credential, Event, Flow, Run
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.settings import settings
from saz.tools.registry import ToolRegistry
from tests.conftest import TEST_USER_ID
from tests.fakes.tools import RecordingTool

SECRET_VALUE = "tok-super-secret-ABC12345"

HTTP_SPEC = {
    "name": "http_request",
    "description": "Fake recorded HTTP",
    "input_schema": {
        "type": "object",
        "properties": {
            "method": {"type": "string"},
            "url": {"type": "string"},
            "headers": {"type": "object"},
            "body": {"type": "object"},
        },
        "required": ["method", "url"],
    },
}


class SpyCritic:
    """Records the tool-call payloads it is asked to verify/critique."""

    def __init__(self) -> None:
        self.verify_payloads: list[Any] = []
        self.critique_payloads: list[Any] = []
        self.usage_recorder = None

    def _pass(self) -> Critique:
        return Critique(
            verdict=Verdict.PASS,
            reasoning="ok",
            issues=[],
            safety_flags=[],
            suggestions={},
            confidence=0.95,
        )

    async def verify_proposal(self, *, proposed_tool_call: Any, **kwargs: Any) -> Critique:
        self.verify_payloads.append(proposed_tool_call)
        return self._pass()

    async def critique(self, *, tool_call: Any, **kwargs: Any) -> Critique:
        self.critique_payloads.append(tool_call)
        return self._pass()


@pytest.fixture
def secret_flow(db_engine, monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "CREDENTIALS_ENCRYPTION_KEY", key)
    with Session(db_engine) as session:
        session.add(
            Credential(
                created_by_user_id=TEST_USER_ID,
                name="ERP_TOKEN",
                type="api_token",
                data_encrypted=Fernet(key.encode()).encrypt(
                    yaml.safe_dump({"token": SECRET_VALUE}).encode()
                ),
            )
        )
        session.add(
            Flow(
                created_by_user_id=TEST_USER_ID,
                id="flow_secret_prompt",
                name="secret_prompt",
                definition={
                    "schema_version": 1,
                    "flow": {"name": "secret_prompt", "description": "secret redaction probe"},
                    "credentials": {"uses": ["ERP_TOKEN"]},
                    "workflow": {
                        "planner_mode": "deterministic",
                        "steps": [
                            {
                                "id": "call",
                                "type": "tool.call",
                                "description": "Call API with a bearer token",
                                "tool": "http_request",
                                "params": {
                                    "method": "POST",
                                    "url": "https://api.example.com/x",
                                    "headers": {
                                        "Authorization": "Bearer {{ $secret('ERP_TOKEN') }}"
                                    },
                                    "body": {"note": "non-secret-marker"},
                                },
                            }
                        ],
                    },
                },
            )
        )
        session.add(
            Run(
                created_by_user_id=TEST_USER_ID,
                id="run_secret_prompt",
                flow_id="flow_secret_prompt",
                status="queued",
                planner_mode="deterministic",
                payload={},
            )
        )
        session.commit()
    return "run_secret_prompt"


def test_secret_value_and_key_redacted_before_critic(secret_flow, db_engine):
    tool = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    registry = ToolRegistry()
    registry.register_custom_tool("http_request", tool.spec, tool.execute)
    critic = SpyCritic()

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
            asyncio.run(executor.execute_run(secret_flow))

    # The tool itself must still have received the real secret (execution path).
    assert tool.call_count == 1
    executed = json.dumps(tool.calls[0])
    assert SECRET_VALUE in executed, "tool execution must receive the real secret"

    # Neither verifier nor critic payload may contain the secret value.
    assert critic.verify_payloads, "verifier was not called"
    assert critic.critique_payloads, "critic was not called"
    for payload in critic.verify_payloads + critic.critique_payloads:
        blob = json.dumps(payload)
        assert SECRET_VALUE not in blob, f"secret leaked into critic payload: {blob}"
        # Sensitive key redacted wholesale, structure preserved.
        args = payload["arguments"]
        assert args["headers"]["Authorization"] == "***REDACTED***"
        # Non-secret fields remain visible so the critic can still reason.
        assert args["body"]["note"] == "non-secret-marker"
        assert args["url"] == "https://api.example.com/x"


def test_secret_value_never_in_persisted_event_payloads(secret_flow, db_engine):
    """End-to-end: run a real flow with a $secret(...) and assert the raw
    secret value never lands in any persisted Event (payload, summary, tags)
    for the run. Events are an audit surface streamed to clients."""
    tool = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    registry = ToolRegistry()
    registry.register_custom_tool("http_request", tool.spec, tool.execute)

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            executor = WorkflowExecutor(
                uow=uow,
                tool_registry=registry,
                planner=DeterministicPlanner(),
                executor_agent=ExecutorAgent(),
                critic=SpyCritic(),  # type: ignore[arg-type]
                policy_engine=PolicyEngine(),
            )
            asyncio.run(executor.execute_run(secret_flow))

    assert tool.call_count == 1, "sanity: the flow actually executed"

    with Session(db_engine) as session:
        events = session.query(Event).filter(Event.run_id == secret_flow).all()
        assert events, "sanity: the run emitted audit events"
        for e in events:
            blob = json.dumps({"summary": e.summary, "payload": e.payload, "tags": e.tags})
            assert (
                SECRET_VALUE not in blob
            ), f"secret leaked into persisted event {e.event_type!r}: {blob}"
