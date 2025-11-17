"""Tests for Ansible Tool with ansible_runner backend."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from saz.tools.ansible_tool import AnsibleTool


@pytest.fixture
def ansible_tool(tmp_path):
    """Create an AnsibleTool instance for testing."""
    artifact_path = tmp_path / "artifacts"
    runner_path = tmp_path / "runner"

    return AnsibleTool(
        allowed_playbook_roots=["/allowed/playbooks"],
        allowed_inventories=["/allowed/inventory.ini"],
        artifact_storage_path=str(artifact_path),
        runner_artifacts_dir=str(runner_path),
    )


@pytest.fixture
def mock_backend_result():
    """Create a mock backend execution result."""
    return {
        "status": "success",
        "mode": "check",
        "recap": {"ok": 5, "changed": 2, "failed": 0},
        "return_code": 0,
        "stdout": "PLAY RECAP\nhost1: ok=5 changed=2 failed=0",
        "events": [{"event": "playbook_on_start", "uuid": "abc123"}],
        "runner_artifacts_dir": "/tmp/test/artifacts",
        "changed": True,
    }


class TestAnsibleTool:
    """Test suite for AnsibleTool."""

    def test_spec(self, ansible_tool):
        """Test tool specification."""
        spec = ansible_tool.spec

        assert spec["name"] == "ansible_run"
        assert "description" in spec
        assert "input_schema" in spec
        assert spec["input_schema"]["required"] == ["mode", "playbook", "inventory"]

    @pytest.mark.asyncio
    async def test_execute_success(self, ansible_tool, mock_backend_result, tmp_path):
        """Test successful playbook execution."""
        with patch.object(
            ansible_tool.backend, "execute", new=AsyncMock(return_value=mock_backend_result)
        ):
            result = await ansible_tool.execute(
                mode="check",
                playbook="/allowed/playbooks/site.yml",
                inventory="/allowed/inventory.ini",
                run_id="test_run",
                step_id="step1",
            )

            # Verify result structure
            assert result["status"] == "success"
            assert result["mode"] == "check"
            assert result["recap"]["ok"] == 5
            assert result["changed"] is True
            assert "artifact_id" in result
            assert "stdout_preview" in result

            # Verify artifact was stored
            artifact_path = ansible_tool.artifact_storage_path / "test_run_step1_ansible.json"
            assert artifact_path.exists()

            # Verify artifact contents
            artifact_data = json.loads(artifact_path.read_text())
            assert artifact_data["mode"] == "check"
            assert artifact_data["playbook"] == "/allowed/playbooks/site.yml"
            assert "events" in artifact_data
            assert "runner_artifacts_dir" in artifact_data

    @pytest.mark.asyncio
    async def test_execute_with_allowlist_validation_playbook(
        self, ansible_tool, mock_backend_result
    ):
        """Test that playbook allowlist is enforced."""
        with patch.object(
            ansible_tool.backend, "execute", new=AsyncMock(return_value=mock_backend_result)
        ):
            # Should fail - playbook not in allowed roots
            with pytest.raises(ValueError) as exc_info:
                await ansible_tool.execute(
                    mode="check",
                    playbook="/disallowed/playbooks/site.yml",
                    inventory="/allowed/inventory.ini",
                    run_id="test_run",
                    step_id="step1",
                )

            assert "not in allowed roots" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_with_allowlist_validation_inventory(
        self, ansible_tool, mock_backend_result
    ):
        """Test that inventory allowlist is enforced."""
        with patch.object(
            ansible_tool.backend, "execute", new=AsyncMock(return_value=mock_backend_result)
        ):
            # Should fail - inventory not in allowed list
            with pytest.raises(ValueError) as exc_info:
                await ansible_tool.execute(
                    mode="check",
                    playbook="/allowed/playbooks/site.yml",
                    inventory="/disallowed/inventory.ini",
                    run_id="test_run",
                    step_id="step1",
                )

            assert "not in allowed inventories" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_with_all_parameters(self, ansible_tool, mock_backend_result):
        """Test execution with all optional parameters."""
        with patch.object(
            ansible_tool.backend, "execute", new=AsyncMock(return_value=mock_backend_result)
        ) as mock_exec:
            await ansible_tool.execute(
                mode="apply",
                playbook="/allowed/playbooks/site.yml",
                inventory="/allowed/inventory.ini",
                limit="web_servers",
                tags=["deploy"],
                skip_tags=["backup"],
                extra_vars={"env": "prod"},
                credentials={"ssh_key": "key_data", "vault_password": "secret"},
                verbosity=2,
                run_id="test_run",
                step_id="step1",
            )

            # Verify backend was called with all parameters
            call_kwargs = mock_exec.call_args.kwargs
            assert call_kwargs["mode"] == "apply"
            assert call_kwargs["limit"] == "web_servers"
            assert call_kwargs["tags"] == ["deploy"]
            assert call_kwargs["skip_tags"] == ["backup"]
            assert call_kwargs["extra_vars"] == {"env": "prod"}
            assert call_kwargs["credentials"]["ssh_key"] == "key_data"
            assert call_kwargs["verbosity"] == 2

    def test_is_allowed_playbook_with_restrictions(self, ansible_tool):
        """Test playbook allowlist checking."""
        # Allowed
        assert ansible_tool._is_allowed_playbook("/allowed/playbooks/site.yml")
        assert ansible_tool._is_allowed_playbook("/allowed/playbooks/subdir/deploy.yml")

        # Not allowed
        assert not ansible_tool._is_allowed_playbook("/other/playbooks/site.yml")
        assert not ansible_tool._is_allowed_playbook("/allowed/site.yml")  # Parent dir

    def test_is_allowed_playbook_no_restrictions(self, tmp_path):
        """Test playbook allowlist checking with no restrictions."""
        tool = AnsibleTool(
            allowed_playbook_roots=[],  # No restrictions
            allowed_inventories=[],
            artifact_storage_path=str(tmp_path / "artifacts"),
        )

        # All playbooks should be allowed
        assert tool._is_allowed_playbook("/any/path/playbook.yml")

    def test_is_allowed_inventory_with_restrictions(self, ansible_tool):
        """Test inventory allowlist checking."""
        # Allowed
        assert ansible_tool._is_allowed_inventory("/allowed/inventory.ini")

        # Not allowed
        assert not ansible_tool._is_allowed_inventory("/other/inventory.ini")
        assert not ansible_tool._is_allowed_inventory("/allowed/other_inventory.ini")

    def test_is_allowed_inventory_no_restrictions(self, tmp_path):
        """Test inventory allowlist checking with no restrictions."""
        tool = AnsibleTool(
            allowed_playbook_roots=[],
            allowed_inventories=[],  # No restrictions
            artifact_storage_path=str(tmp_path / "artifacts"),
        )

        # All inventories should be allowed
        assert tool._is_allowed_inventory("/any/path/inventory.ini")

    @pytest.mark.asyncio
    async def test_execute_backend_failure_propagation(self, ansible_tool):
        """Test that backend failures are propagated correctly."""
        with patch.object(
            ansible_tool.backend,
            "execute",
            new=AsyncMock(side_effect=RuntimeError("Playbook failed")),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                await ansible_tool.execute(
                    mode="apply",
                    playbook="/allowed/playbooks/site.yml",
                    inventory="/allowed/inventory.ini",
                    run_id="test_run",
                    step_id="step1",
                )

            assert "Playbook failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_artifact_storage_creates_directory(self, tmp_path):
        """Test that artifact storage directory is created."""
        artifact_path = tmp_path / "new_artifacts"
        assert not artifact_path.exists()

        AnsibleTool(
            allowed_playbook_roots=["/allowed"],
            allowed_inventories=["/allowed/inventory.ini"],
            artifact_storage_path=str(artifact_path),
        )

        # Directory should be created
        assert artifact_path.exists()
        assert artifact_path.is_dir()
