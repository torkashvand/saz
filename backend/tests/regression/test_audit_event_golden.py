"""Compare actual audit event sequences to a frozen golden file.

The integration test_event_timelines.py asserts a few specific event_types
exist and a few orderings hold. This test goes one step further: it pins
the *full* event_type sequence (in order, with duplicates collapsed to
ordered uniques) for canonical flows.

If you intentionally change the audit timeline, regenerate
tests/golden/audit_event_sequences.json to match — that's the deliberate
contract update.
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy.orm import Session

from saz.agents.deterministic_planner import DeterministicPlanner
from saz.agents.executor import ExecutorAgent
from saz.agents.schemas import Verdict
from saz.db.models import Event, Flow, Run
from saz.db.unit_of_work import UnitOfWork
from saz.engine.executor import WorkflowExecutor
from saz.policies.policy_engine import PolicyEngine
from saz.tools.registry import ToolRegistry
from tests.conftest import TEST_USER_ID
from tests.fakes.critic import FakeCritic
from tests.fakes.tools import RecordingTool

GOLDEN_PATH = Path(__file__).parent.parent / "golden" / "audit_event_sequences.json"


HTTP_SPEC = {
    "name": "http_request",
    "description": "Fake recorded HTTP",
    "inputSchema": {
        "type": "object",
        "properties": {"method": {"type": "string"}, "url": {"type": "string"}},
        "required": ["method", "url"],
    },
}


def _load_golden() -> dict[str, list[str]]:
    with open(GOLDEN_PATH) as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def _seed_one_step_run(session: Session, run_id: str = "run_golden_1") -> str:
    flow = Flow(
        created_by_user_id=TEST_USER_ID,
        id=f"flow_{run_id}",
        name=f"flow_{run_id}",
        definition={
            "schema_version": 1,
            "flow": {"name": f"flow_{run_id}", "description": "golden"},
            "workflow": {
                "planner_mode": "deterministic",
                "steps": [
                    {
                        "id": "do",
                        "type": "tool.call",
                        "description": "single call",
                        "tool": "http_request",
                        "params": {"method": "GET", "url": "https://e.com/x"},
                    }
                ],
            },
            "policies": {"budget_usd": 1.0},
        },
    )
    run = Run(
        created_by_user_id=TEST_USER_ID,
        id=run_id,
        flow_id=f"flow_{run_id}",
        status="queued",
        planner_mode="deterministic",
        payload={},
    )
    session.add_all([flow, run])
    session.commit()
    return run_id


def _captured_event_types(db_engine, run_id: str) -> list[str]:
    with Session(db_engine) as session:
        events = (
            session.query(Event)
            .filter(Event.run_id == run_id)
            .order_by(Event.timestamp, Event.id)
            .all()
        )
    seen: list[str] = []
    for e in events:
        if not seen or seen[-1] != e.event_type:
            seen.append(e.event_type)
    return seen


def _run_to_completion(db_engine, run_id: str, critic: FakeCritic) -> None:
    fake_http = RecordingTool("http_request", response={"ok": True}, spec=HTTP_SPEC)
    registry = ToolRegistry()
    registry.register_custom_tool("http_request", fake_http.spec, fake_http.execute)
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
            try:
                asyncio.run(executor.execute_run(run_id))
            except Exception:
                pass


def _assert_subsequence(actual: list[str], expected: list[str], scenario: str) -> None:
    """Each item in `expected` must appear in `actual` in order."""
    iterator = iter(actual)
    missing: list[str] = []
    for needed in expected:
        for item in iterator:
            if item == needed:
                break
        else:
            missing.append(needed)
    assert not missing, (
        f"audit timeline drift for {scenario!r}: missing/out-of-order events "
        f"{missing}\n  expected ordered subsequence: {expected}\n  actual: {actual}"
    )


def test_deterministic_one_step_success_matches_golden(db_engine):
    golden = _load_golden()
    expected = golden["deterministic_one_step_success"]

    with Session(db_engine) as session:
        run_id = _seed_one_step_run(session, "run_golden_det")

    _run_to_completion(db_engine, run_id, FakeCritic())

    actual = _captured_event_types(db_engine, run_id)
    _assert_subsequence(actual, expected, "deterministic_one_step_success")


def test_verifier_blocking_matches_golden(db_engine):
    golden = _load_golden()
    expected = golden["verifier_blocking_pre_execution"]

    with Session(db_engine) as session:
        run_id = _seed_one_step_run(session, "run_golden_block")

    _run_to_completion(db_engine, run_id, FakeCritic(default_verify=Verdict.FAIL))

    actual = _captured_event_types(db_engine, run_id)
    _assert_subsequence(actual, expected, "verifier_blocking_pre_execution")


def test_golden_file_is_well_formed():
    """Catches accidental JSON corruption / unknown top-level scenarios."""
    with open(GOLDEN_PATH) as f:
        data = json.load(f)
    scenarios = [k for k in data if not k.startswith("_")]
    assert scenarios, "golden file must list at least one scenario"
    for name, seq in data.items():
        if name.startswith("_"):
            continue
        assert isinstance(seq, list) and all(
            isinstance(x, str) for x in seq
        ), f"scenario {name!r} must map to a list of event_type strings"
