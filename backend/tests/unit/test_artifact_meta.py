"""Download metadata derivation for stored artifacts."""

from saz.engine.executor import _build_artifact_meta


def test_docx_render_meta():
    result = {
        "artifact_id": "a1",
        "name": "rfq_final_T88815",
        "path": "/tmp/saz/artifacts/a1_rfq_final_T88815.docx",
        "byte_size": 109132,
    }
    meta = _build_artifact_meta("docx_render", result)
    assert meta["blob_ref"] == result["path"]
    assert meta["filename"] == "rfq_final_T88815.docx"
    assert meta["content_type"].endswith("wordprocessingml.document")
    assert meta["size_bytes"] == 109132


def test_artifact_store_json_meta(tmp_path):
    f = tmp_path / "rec.json"
    f.write_text('{"x": 1}')
    result = {
        "artifact_id": "a2",
        "name": "rfq_audit_T88815",
        "storage_path": str(f),
        "content_type": "json",
    }
    meta = _build_artifact_meta("artifact.store", result)
    assert meta["blob_ref"] == str(f)
    assert meta["filename"] == "rfq_audit_T88815.json"
    assert meta["content_type"] == "application/json"
    assert meta["size_bytes"] == f.stat().st_size
