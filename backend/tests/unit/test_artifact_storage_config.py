"""Artifact storage path must be configurable, not a hardcoded /tmp location."""

from saz.settings import Settings
from saz.tools.registry import create_default_registry


def test_default_artifact_path_is_persistent_not_tmp():
    s = Settings()
    assert s.ARTIFACT_STORAGE_PATH
    assert not s.ARTIFACT_STORAGE_PATH.startswith("/tmp")


def test_registry_honors_configured_artifact_path(tmp_path):
    # The configured path must flow through to the tools that write files,
    # so artifacts land where the operator configured (not /tmp).
    registry = create_default_registry(enable_ai_ops=False, artifact_storage_path=str(tmp_path))
    for tool_name in ("docx_render", "artifact.store"):
        executor = registry._executors[tool_name]
        assert str(executor.__self__.storage_path) == str(tmp_path)
