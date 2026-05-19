"""Unit tests for ArtifactTool (filesystem storage backend).

These tests exercise the tool in isolation — no executor, no DB. They
pin the JSON-on-disk contract (artifact_id, name, content, content_type,
metadata, created_at) and ensure list_artifacts respects the run_id
filter without leaking content.
"""

import asyncio
import json
from pathlib import Path

import pytest

from saz.tools.artifact_tool import ArtifactTool


@pytest.fixture
def tool(tmp_path: Path) -> ArtifactTool:
    return ArtifactTool(storage_path=str(tmp_path / "artifacts"))


def test_artifact_tool_store_writes_json_file_with_full_record(tool: ArtifactTool) -> None:
    result = asyncio.run(
        tool.store(
            name="final_report",
            content={"score": 0.91, "rows": [1, 2, 3]},
            content_type="json",
            metadata={"source": "test"},
            run_id="run-A",
            step_id="step-1",
        )
    )

    assert result["status"] == "stored"
    assert result["name"] == "final_report"
    artifact_id = result["artifact_id"]
    assert artifact_id
    path = Path(result["storage_path"])
    assert path.exists()

    with open(path) as f:
        record = json.load(f)
    assert record["artifact_id"] == artifact_id
    assert record["name"] == "final_report"
    assert record["content"] == {"score": 0.91, "rows": [1, 2, 3]}
    assert record["content_type"] == "json"
    assert record["metadata"] == {"source": "test"}
    assert record["run_id"] == "run-A"
    assert record["step_id"] == "step-1"
    assert "created_at" in record


def test_artifact_tool_retrieve_round_trips_stored_content(tool: ArtifactTool) -> None:
    stored = asyncio.run(tool.store(name="r", content={"v": 1}, run_id="run-A", step_id="s"))
    record = asyncio.run(tool.retrieve(stored["artifact_id"]))
    assert record["artifact_id"] == stored["artifact_id"]
    assert record["content"] == {"v": 1}
    assert record["run_id"] == "run-A"


def test_artifact_tool_retrieve_missing_artifact_raises(tool: ArtifactTool) -> None:
    with pytest.raises(FileNotFoundError) as exc:
        asyncio.run(tool.retrieve("nonexistent-id"))
    assert "nonexistent-id" in str(exc.value)


def test_artifact_tool_list_artifacts_empty_directory_returns_empty_list(
    tool: ArtifactTool,
) -> None:
    out = asyncio.run(tool.list_artifacts())
    assert out == []


def test_artifact_tool_list_artifacts_returns_metadata_without_content(
    tool: ArtifactTool,
) -> None:
    a = asyncio.run(tool.store(name="a", content={"v": 1}, run_id="r1", step_id="s1"))
    b = asyncio.run(tool.store(name="b", content={"v": 2}, run_id="r2", step_id="s2"))

    out = asyncio.run(tool.list_artifacts())

    by_id = {item["artifact_id"]: item for item in out}
    assert a["artifact_id"] in by_id
    assert b["artifact_id"] in by_id
    sample = by_id[a["artifact_id"]]
    assert sample["name"] == "a"
    assert sample["run_id"] == "r1"
    assert sample["step_id"] == "s1"
    assert sample["content_type"] == "json"
    # List view must NOT include content payload — it's metadata-only.
    assert "content" not in sample


def test_artifact_tool_list_artifacts_filters_by_run_id(tool: ArtifactTool) -> None:
    asyncio.run(tool.store(name="a", content={"v": 1}, run_id="r1"))
    asyncio.run(tool.store(name="b", content={"v": 2}, run_id="r2"))
    asyncio.run(tool.store(name="c", content={"v": 3}, run_id="r1"))

    only_r1 = asyncio.run(tool.list_artifacts(run_id="r1"))
    assert len(only_r1) == 2
    assert all(item["run_id"] == "r1" for item in only_r1)


def test_artifact_tool_list_artifacts_skips_corrupt_json_silently(
    tool: ArtifactTool, tmp_path: Path
) -> None:
    """A malformed JSON file in the storage dir must not blow up the listing
    — operators rely on the list view to remain available even when one
    artifact got truncated mid-write."""
    asyncio.run(tool.store(name="ok", content={"v": 1}, run_id="r1"))

    bad = tool.storage_path / "corrupt.json"
    bad.write_text("{not json")

    out = asyncio.run(tool.list_artifacts())
    # Only the well-formed record should be returned.
    assert len(out) == 1
    assert out[0]["name"] == "ok"


def test_artifact_tool_specs_advertise_required_fields(tool: ArtifactTool) -> None:
    """The MCP spec is what the executor reads to validate tool inputs — it
    must list ``name`` and ``content`` as required for store, and
    ``artifact_id`` as required for retrieve."""
    store_spec = tool.store_spec
    assert store_spec["name"] == "artifact.store"
    assert set(store_spec["inputSchema"]["required"]) == {"name", "content"}

    retrieve_spec = tool.retrieve_spec
    assert retrieve_spec["name"] == "artifact.retrieve"
    assert retrieve_spec["inputSchema"]["required"] == ["artifact_id"]
