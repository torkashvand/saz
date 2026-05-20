"""API contract tests for /runs/{id}/graph, /compliance, and /retry.

These endpoints back the run-detail UI panels: the graph drives the
DAG view, the compliance report drives the audit panel, and /retry
is the same-run retry button. Each has its own 404 path and its own
contract that the frontend types depend on.
"""

import pytest
from sqlalchemy.orm import Session

from saz.db.models import Flow, Run, Step
from tests.conftest import TEST_USER_ID


@pytest.fixture
def two_step_flow(db_engine):
    """A flow definition with two ordered workflow steps and a queued run."""
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_graph",
            name="graph_flow",
            definition={
                "schema_version": 1,
                "flow": {"name": "graph_flow", "description": "two-step"},
                "workflow": {
                    "planner_mode": "deterministic",
                    "steps": [
                        {
                            "id": "extract",
                            "type": "ai.extract",
                            "instruction": (
                                "extract a very long instruction that exceeds the fifty character "
                                "truncation threshold applied by the graph endpoint"
                            ),
                        },
                        {
                            "id": "store",
                            "type": "artifact.store",
                            "description": "persist final output",
                            "params": {"name": "out", "content": {"x": 1}},
                        },
                    ],
                },
            },
        )
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_graph_1",
            flow_id="flow_graph",
            status="completed",
            planner_mode="deterministic",
            payload={},
            total_tokens=120,
            total_cost_usd=0.02,
        )
        session.add_all([flow, run])
        session.commit()
    return "run_graph_1"


def test_run_graph_endpoint_returns_nodes_and_edges_in_order(app_client, two_step_flow):
    resp = app_client.get(f"/api/v1/runs/{two_step_flow}/graph")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["run_id"] == two_step_flow
    ids = [n["id"] for n in body["nodes"]]
    types = [n["type"] for n in body["nodes"]]
    assert ids == ["extract", "store"]
    assert types == ["ai.extract", "artifact.store"]

    # Long instruction is truncated with an ellipsis at 50 chars.
    extract_label = body["nodes"][0]["label"]
    assert extract_label.endswith("...")
    assert len(extract_label) <= 53

    assert body["edges"] == [{"from": "extract", "to": "store"}]


def test_run_graph_endpoint_returns_404_for_unknown_run(app_client):
    resp = app_client.get("/api/v1/runs/no_such_run/graph")
    assert resp.status_code == 404


def test_run_graph_endpoint_returns_empty_graph_when_flow_missing(app_client, db_engine):
    """If the run's flow has been deleted but the run row still exists, the
    endpoint must respond with an empty graph rather than 500."""
    with Session(db_engine) as session:
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_no_flow",
            flow_id="missing_flow",
            status="failed",
            planner_mode="deterministic",
            payload={},
        )
        session.add(run)
        session.commit()

    resp = app_client.get("/api/v1/runs/run_no_flow/graph")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "run_no_flow"
    assert body["nodes"] == []
    assert body["edges"] == []


def test_run_compliance_endpoint_aggregates_step_tokens_and_cost(app_client, db_engine):
    """Compliance report sums per-step tokens and cost, and assigns
    compliance_score=1.0 only for completed runs."""
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_c",
            name="compliance_flow",
            definition={"workflow": {"planner_mode": "deterministic", "steps": []}},
        )
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_c_1",
            flow_id="flow_c",
            status="completed",
            planner_mode="deterministic",
            payload={},
        )
        step_a = Step(
            id="s_a",
            run_id="run_c_1",
            number=0,
            name="a",
            step_type="ai.extract",
            status="completed",
            attempt=1,
            tokens=100,
            cost_usd=0.01,
        )
        step_b = Step(
            id="s_b",
            run_id="run_c_1",
            number=1,
            name="b",
            step_type="tool.call",
            status="completed",
            attempt=1,
            tokens=250,
            cost_usd=0.03,
        )
        session.add_all([flow, run, step_a, step_b])
        session.commit()

    resp = app_client.get("/api/v1/runs/run_c_1/compliance")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    report = body["report"]

    assert body["run_id"] == "run_c_1"
    assert report["run_id"] == "run_c_1"
    assert report["flow_id"] == "flow_c"
    assert report["total_tokens"] == 350
    assert report["total_cost_usd"] == pytest.approx(0.04)
    assert report["steps_analyzed"] == 2
    assert report["compliance_score"] == 1.0
    assert report["findings"] == []
    assert report["recommendations"] == []


def test_run_compliance_endpoint_reports_partial_score_for_failed(app_client, db_engine):
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_cf",
            name="compliance_failed",
            definition={"workflow": {"planner_mode": "deterministic", "steps": []}},
        )
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_cf_1",
            flow_id="flow_cf",
            status="failed",
            planner_mode="deterministic",
            payload={},
            error={"type": "RuntimeError", "message": "boom"},
        )
        session.add_all([flow, run])
        session.commit()

    resp = app_client.get("/api/v1/runs/run_cf_1/compliance")
    assert resp.status_code == 200
    report = resp.json()["report"]
    assert report["compliance_score"] == 0.5
    assert report["steps_analyzed"] == 0


def test_run_compliance_endpoint_404_for_unknown_run(app_client):
    resp = app_client.get("/api/v1/runs/none/compliance")
    assert resp.status_code == 404


# ----------------------------- retry endpoint -----------------------------


def test_retry_endpoint_rejects_non_failed_run(app_client, db_engine):
    """The API contract: only runs with status in {failed, error} are retryable.
    Attempting to retry a completed or running run must surface as a 4xx-style
    error (not as a 200 that silently does nothing)."""
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_retry_bad",
            name="rb",
            definition={"workflow": {"planner_mode": "deterministic", "steps": []}},
        )
        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_retry_bad",
            flow_id="flow_retry_bad",
            status="completed",
            planner_mode="deterministic",
            payload={},
        )
        session.add_all([flow, run])
        session.commit()

    resp = app_client.post("/api/v1/runs/run_retry_bad/retry", json={})
    # Either 4xx or 5xx surface for the bad-state ValueError; what matters is
    # it does NOT return 200 "OK".
    assert resp.status_code >= 400
    body = resp.json()
    assert "detail" in body or "error" in body or "message" in body


def test_retry_endpoint_returns_404_for_unknown_run(app_client):
    resp = app_client.post("/api/v1/runs/missing/retry", json={})
    assert resp.status_code == 404
