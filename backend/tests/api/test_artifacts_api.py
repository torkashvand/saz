"""Artifact list + download API: a user can see and download a run's outputs."""

from sqlalchemy.orm import Session

from saz.db.models import Artifact, Flow, Run, User
from tests.conftest import TEST_USER_ID

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _seed(session, *, owner_id, blob_ref, run_id, flow_id, art_id="art-1"):
    session.add(
        Flow(
            created_by_user_id=owner_id,
            id=flow_id,
            name=f"flow-{run_id}",
            definition={"workflow": {"planner_mode": "deterministic", "steps": []}},
        )
    )
    session.add(
        Run(
            created_by_user_id=owner_id,
            id=run_id,
            flow_id=flow_id,
            status="completed",
            planner_mode="deterministic",
            payload={},
        )
    )
    session.add(
        Artifact(
            id=art_id,
            run_id=run_id,
            step_id=None,
            name="rfq_final",
            blob_ref=str(blob_ref),
            meta={
                "artifact_id": "x",
                "content_type": _DOCX_MIME,
                "filename": "rfq_final_T88815.docx",
                "size_bytes": (blob_ref.stat().st_size if blob_ref.exists() else 0),
            },
        )
    )
    session.commit()


def test_list_and_download_artifact(app_client, db_engine, tmp_path):
    doc = tmp_path / "out.docx"
    doc.write_bytes(b"PK\x03\x04 fake-docx-bytes")
    with Session(db_engine) as s:
        _seed(s, owner_id=TEST_USER_ID, blob_ref=doc, run_id="run-ok", flow_id="flow-ok")

    # list
    r = app_client.get("/api/v1/runs/run-ok/artifacts")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "run-ok"
    assert len(body["artifacts"]) == 1
    item = body["artifacts"][0]
    assert item["filename"] == "rfq_final_T88815.docx"
    assert item["content_type"] == _DOCX_MIME
    assert item["size_bytes"] == doc.stat().st_size

    # download
    d = app_client.get(f"/api/v1/runs/run-ok/artifacts/{item['id']}/download")
    assert d.status_code == 200
    assert d.content == doc.read_bytes()
    assert d.headers["content-type"] == _DOCX_MIME
    assert "attachment" in d.headers["content-disposition"]
    assert "rfq_final_T88815.docx" in d.headers["content-disposition"]


def test_download_forbidden_for_another_users_run(app_client, db_engine, tmp_path):
    doc = tmp_path / "other.docx"
    doc.write_bytes(b"secret")
    with Session(db_engine) as s:
        s.add(
            User(
                id="11111111-1111-1111-1111-111111111111",
                username="other",
                email="other@example.com",
                password_hash="x",
            )
        )
        s.commit()
        _seed(
            s,
            owner_id="11111111-1111-1111-1111-111111111111",
            blob_ref=doc,
            run_id="run-other",
            flow_id="flow-other",
            art_id="art-other",
        )

    assert app_client.get("/api/v1/runs/run-other/artifacts").status_code == 403
    assert app_client.get("/api/v1/runs/run-other/artifacts/art-other/download").status_code == 403


def test_download_missing_file_is_404(app_client, db_engine, tmp_path):
    with Session(db_engine) as s:
        _seed(
            s,
            owner_id=TEST_USER_ID,
            blob_ref=tmp_path / "gone.docx",  # never created
            run_id="run-missing",
            flow_id="flow-missing",
            art_id="art-missing",
        )
    assert (
        app_client.get("/api/v1/runs/run-missing/artifacts/art-missing/download").status_code == 404
    )
