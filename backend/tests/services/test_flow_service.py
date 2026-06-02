"""FlowService unit tests.

The service is the single entry point all flow registrations flow
through (API + future programmatic callers). These tests pin invariants
at the service layer rather than only via the HTTP route, so a future
refactor that bypasses the route still triggers them.
"""

import pytest
from sqlalchemy.orm import Session

from saz.db.unit_of_work import UnitOfWork
from saz.services.flow_service import FlowService
from tests.conftest import TEST_USER_ID

VALID_YAML = """
schema_version: 1
flow:
  name: svc_flow_test
  description: Service-layer test flow
workflow:
  planner_mode: deterministic
  steps:
    - id: extract
      type: ai.extract
      instruction: Extract data
      expect:
        properties:
          field: { type: string }
        required: [field]
"""

INVALID_AI_YAML = """
schema_version: 1
flow:
  name: svc_invalid_ai
  description: AI step missing expect
workflow:
  planner_mode: deterministic
  steps:
    - id: extract
      type: ai.extract
      instruction: Extract data
"""


def _service(db_engine) -> tuple[FlowService, Session, UnitOfWork]:
    session = Session(db_engine)
    uow = UnitOfWork(session).__enter__()
    return FlowService(uow), session, uow


def test_register_rejects_invalid_dsl(db_engine):
    service, session, uow = _service(db_engine)
    try:
        with pytest.raises(ValueError):
            service.register(INVALID_AI_YAML, created_by_user_id=TEST_USER_ID)
    finally:
        uow.__exit__(None, None, None)
        session.close()


BAD_TOOL_YAML = """
schema_version: 1
flow:
  name: svc_bad_tool
  description: References a tool that is not registered
workflow:
  planner_mode: deterministic
  steps:
    - id: store
      type: tool.call
      tool: artifact_store
      description: wrong name, should be artifact.store
      params:
        name: r
        content_type: json
        content: {}
"""

GOOD_TOOL_YAML = BAD_TOOL_YAML.replace("svc_bad_tool", "svc_good_tool").replace(
    "tool: artifact_store", "tool: artifact.store"
)


class _StubRegistry:
    def list_tools(self):
        return ["http_request", "artifact.store", "ansible_run"]


def test_register_rejects_unknown_tool_name(db_engine, monkeypatch):
    monkeypatch.setattr("saz.globals.get_tool_registry", lambda: _StubRegistry())
    service, session, uow = _service(db_engine)
    try:
        with pytest.raises(ValueError, match="Unknown tool"):
            service.register(BAD_TOOL_YAML, created_by_user_id=TEST_USER_ID)
    finally:
        uow.__exit__(None, None, None)
        session.close()


def test_register_accepts_known_tool_name(db_engine, monkeypatch):
    monkeypatch.setattr("saz.globals.get_tool_registry", lambda: _StubRegistry())
    service, session, uow = _service(db_engine)
    try:
        flow_id = service.register(GOOD_TOOL_YAML, created_by_user_id=TEST_USER_ID)
        assert flow_id
    finally:
        uow.__exit__(None, None, None)
        session.close()


def test_register_persists_valid_flow_and_returns_id(db_engine):
    service, session, uow = _service(db_engine)
    try:
        flow_id = service.register(VALID_YAML, created_by_user_id=TEST_USER_ID)
        assert flow_id, "register must return a non-empty id"
        detail = service.get(flow_id)
        assert detail is not None
        assert detail.name == "svc_flow_test"
    finally:
        uow.__exit__(None, None, None)
        session.close()


def test_register_same_name_updates_existing_flow(db_engine):
    """Re-registering a flow by name updates rather than creating a duplicate."""
    service, session, uow = _service(db_engine)
    try:
        first_id = service.register(VALID_YAML, created_by_user_id=TEST_USER_ID)
        second_id = service.register(VALID_YAML, created_by_user_id=TEST_USER_ID)
        assert first_id == second_id, (
            "Re-registering the same flow name must update the existing row, "
            f"got first_id={first_id!r} second_id={second_id!r}"
        )
    finally:
        uow.__exit__(None, None, None)
        session.close()


def test_get_returns_none_for_unknown_id(db_engine):
    service, session, uow = _service(db_engine)
    try:
        assert service.get("flow_does_not_exist") is None
    finally:
        uow.__exit__(None, None, None)
        session.close()
