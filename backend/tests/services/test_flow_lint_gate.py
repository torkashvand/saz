"""FlowService consistency-lint gate: blocking, persistence, and overrides."""

import json

import pytest
from sqlalchemy.orm import Session

from saz.agents.llm_port import LLMPort, LLMResponse
from saz.api.errors import FlowLintError
from saz.db.unit_of_work import UnitOfWork
from saz.services.flow_service import FlowService
from saz.settings import settings
from tests.conftest import TEST_USER_ID

# prose says 3-6 items, schema only enforces minItems:1 → PROSE_SCHEMA_COUNT_MISMATCH
COUNT_MISMATCH_YAML = """
schema_version: 1
flow:
  name: lint_gate_count
  description: count mismatch flow
workflow:
  planner_mode: deterministic
  steps:
    - id: summarize
      type: ai.extract
      instruction: |
        Rules:
        - "pre_checks" is a short ordered list (3-6 items) to verify.
      expect:
        type: object
        properties:
          pre_checks:
            type: array
            items: { type: string }
            minItems: 1
        required: [pre_checks]
"""

FIXED_YAML = COUNT_MISMATCH_YAML.replace("minItems: 1", "minItems: 3\n            maxItems: 6")

OVERRIDE_YAML = """
schema_version: 1
flow:
  name: lint_gate_override
  description: overridden count mismatch
workflow:
  planner_mode: deterministic
  steps:
    - id: summarize
      type: ai.extract
      instruction: |
        Rules:
        - "pre_checks" is a short ordered list (3-6 items) to verify.
      lint_ignore:
        - code: PROSE_SCHEMA_COUNT_MISMATCH
          reason: schema intentionally lenient
      expect:
        type: object
        properties:
          pre_checks:
            type: array
            items: { type: string }
            minItems: 1
        required: [pre_checks]
"""

TYPO_OVERRIDE_YAML = OVERRIDE_YAML.replace(
    "name: lint_gate_override", "name: lint_gate_typo"
).replace("PROSE_SCHEMA_COUNT_MISMATCH\n", "PROSE_SCHEMA_COUNT_MISMATC\n")


def _service(db_engine) -> tuple[FlowService, Session, UnitOfWork]:
    session = Session(db_engine)
    uow = UnitOfWork(session).__enter__()
    return FlowService(uow), session, uow


def test_count_mismatch_blocks_and_does_not_persist(db_engine):
    service, session, uow = _service(db_engine)
    try:
        with pytest.raises(FlowLintError) as exc:
            service.register(COUNT_MISMATCH_YAML, created_by_user_id=TEST_USER_ID)
        codes = {f["code"] for f in exc.value.findings}
        assert "PROSE_SCHEMA_COUNT_MISMATCH" in codes
        assert exc.value.status_code == 422
        # nothing persisted
        assert service.get_by_name("lint_gate_count") is None
    finally:
        uow.__exit__(None, None, None)
        session.close()


def test_fixed_schema_registers(db_engine):
    service, session, uow = _service(db_engine)
    try:
        fid = service.register(FIXED_YAML, created_by_user_id=TEST_USER_ID)
        assert service.get(fid) is not None
    finally:
        uow.__exit__(None, None, None)
        session.close()


def test_override_with_reason_registers(db_engine):
    service, session, uow = _service(db_engine)
    try:
        fid = service.register(OVERRIDE_YAML, created_by_user_id=TEST_USER_ID)
        assert service.get(fid) is not None
    finally:
        uow.__exit__(None, None, None)
        session.close()


def test_typo_override_code_blocks(db_engine):
    service, session, uow = _service(db_engine)
    try:
        with pytest.raises(FlowLintError) as exc:
            service.register(TYPO_OVERRIDE_YAML, created_by_user_id=TEST_USER_ID)
        codes = {f["code"] for f in exc.value.findings}
        # the typo'd ignore is itself an error AND the real finding still fires
        assert "LINT_IGNORE_UNKNOWN_CODE" in codes
        assert "PROSE_SCHEMA_COUNT_MISMATCH" in codes
        assert service.get_by_name("lint_gate_typo") is None
    finally:
        uow.__exit__(None, None, None)
        session.close()


# Deterministically clean, but the LLM flags a semantic cross-field issue.
LLM_ONLY_YAML = """
schema_version: 1
flow:
  name: lint_gate_llm
  description: llm-only finding
workflow:
  planner_mode: deterministic
  steps:
    - id: summarize
      type: ai.extract
      instruction: risk_level must be at least the requester's risk_hint.
      expect:
        type: object
        properties:
          risk_level: { type: string }
        required: [risk_level]
"""


class _LLMFlagging(LLMPort):
    async def complete(self, *args, **kwargs) -> LLMResponse:  # type: ignore[override]
        payload = {
            "findings": [
                {
                    "code": "LLM_CROSS_FIELD_RULE_UNENFORCED",
                    "step_id": "summarize",
                    "field": "instruction",
                    "message": "risk_hint→risk_level rule not enforceable by schema",
                    "confidence": 0.9,
                }
            ]
        }
        return LLMResponse(content=json.dumps(payload), total_tokens=5, model="fake")


def test_llm_finding_blocks_through_gate(db_engine, monkeypatch):
    monkeypatch.setattr(settings, "LINT_LLM_ENABLED", True)
    monkeypatch.setattr("saz.agents.llm_port.get_llm_port", lambda: _LLMFlagging())
    service, session, uow = _service(db_engine)
    try:
        with pytest.raises(FlowLintError) as exc:
            service.register(LLM_ONLY_YAML, created_by_user_id=TEST_USER_ID)
        assert exc.value.llm_ran is True
        codes = {f["code"] for f in exc.value.findings}
        assert "LLM_CROSS_FIELD_RULE_UNENFORCED" in codes
        assert service.get_by_name("lint_gate_llm") is None
    finally:
        uow.__exit__(None, None, None)
        session.close()
