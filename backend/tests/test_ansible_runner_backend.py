"""Tests for Ansible Runner Backend."""

from unittest.mock import Mock, patch

import pytest

from saz.tools.ansible_runner_backend import AnsibleRunnerBackend


@pytest.fixture
def backend():
    """Create an AnsibleRunnerBackend instance for testing."""
    return AnsibleRunnerBackend(runner_artifacts_dir="/tmp/test_ansible_runner")


@pytest.fixture
def mock_runner():
    """Create a mock ansible_runner.Runner object."""
    runner = Mock()
    runner.status = "successful"
    runner.rc = 0
    runner.stdout = Mock()
    runner.stdout.read = Mock(return_value="PLAY RECAP\nhost1: ok=5 changed=2 failed=0")
    runner.stderr = None
    runner.stats = {
        "host1": {
            "ok": 5,
            "changed": 2,
            "unreachable": 0,
            "failed": 0,
            "skipped": 1,
            "rescued": 0,
            "ignored": 0,
        }
    }
    runner.events = []
    runner.config = Mock()
    runner.config.artifact_dir = "/tmp/test_ansible_runner/artifacts"
    return runner


class TestAnsibleRunnerBackend:
    """Test suite for AnsibleRunnerBackend."""

    @pytest.mark.asyncio
    async def test_execute_check_mode(self, backend, mock_runner):
        """Test execution in check mode."""
        with patch("ansible_runner.run", return_value=mock_runner) as mock_run:
            result = await backend.execute(
                mode="check",
                playbook="/path/to/playbook.yml",
                inventory="/path/to/inventory",
                run_id="test_run",
                step_id="test_step",
            )

            # Verify ansible_runner.run was called
            assert mock_run.called
            call_kwargs = mock_run.call_args.kwargs

            # Verify check mode flags are in cmdline
            assert "--check" in call_kwargs["cmdline"]
            assert "--diff" in call_kwargs["cmdline"]

            # Verify result structure
            assert result["status"] == "success"
            assert result["mode"] == "check"
            assert result["return_code"] == 0
            assert result["recap"]["ok"] == 5
            assert result["recap"]["changed"] == 2
            assert result["changed"] is True

    @pytest.mark.asyncio
    async def test_execute_apply_mode(self, backend, mock_runner):
        """Test execution in apply mode."""
        with patch("ansible_runner.run", return_value=mock_runner) as mock_run:
            result = await backend.execute(
                mode="apply",
                playbook="/path/to/playbook.yml",
                inventory="/path/to/inventory",
                run_id="test_run",
                step_id="test_step",
            )

            # Verify ansible_runner.run was called
            assert mock_run.called
            call_kwargs = mock_run.call_args.kwargs

            # Verify check mode flags are NOT in cmdline for apply
            assert "--check" not in call_kwargs["cmdline"]

            # Verify result
            assert result["status"] == "success"
            assert result["mode"] == "apply"

    @pytest.mark.asyncio
    async def test_execute_with_limit(self, backend, mock_runner):
        """Test execution with host limit."""
        with patch("ansible_runner.run", return_value=mock_runner) as mock_run:
            await backend.execute(
                mode="apply",
                playbook="/path/to/playbook.yml",
                inventory="/path/to/inventory",
                limit="web_servers",
                run_id="test_run",
                step_id="test_step",
            )

            call_kwargs = mock_run.call_args.kwargs
            assert "--limit web_servers" in call_kwargs["cmdline"]

    @pytest.mark.asyncio
    async def test_execute_with_tags(self, backend, mock_runner):
        """Test execution with tags."""
        with patch("ansible_runner.run", return_value=mock_runner) as mock_run:
            await backend.execute(
                mode="apply",
                playbook="/path/to/playbook.yml",
                inventory="/path/to/inventory",
                tags=["deploy", "configure"],
                run_id="test_run",
                step_id="test_step",
            )

            call_kwargs = mock_run.call_args.kwargs
            assert "--tags deploy,configure" in call_kwargs["cmdline"]

    @pytest.mark.asyncio
    async def test_execute_with_skip_tags(self, backend, mock_runner):
        """Test execution with skip tags."""
        with patch("ansible_runner.run", return_value=mock_runner) as mock_run:
            await backend.execute(
                mode="apply",
                playbook="/path/to/playbook.yml",
                inventory="/path/to/inventory",
                skip_tags=["backup", "cleanup"],
                run_id="test_run",
                step_id="test_step",
            )

            call_kwargs = mock_run.call_args.kwargs
            assert "--skip-tags backup,cleanup" in call_kwargs["cmdline"]

    @pytest.mark.asyncio
    async def test_execute_with_credentials(self, backend, mock_runner):
        """Test execution with SSH key and vault password credentials."""
        with patch("ansible_runner.run", return_value=mock_runner) as mock_run:
            with patch("tempfile.NamedTemporaryFile") as mock_temp:
                # Mock temp file creation
                ssh_file = Mock()
                ssh_file.name = "/tmp/test_ssh_key"
                ssh_file.write = Mock()
                ssh_file.close = Mock()

                vault_file = Mock()
                vault_file.name = "/tmp/test_vault"
                vault_file.write = Mock()
                vault_file.close = Mock()

                mock_temp.side_effect = [ssh_file, vault_file]

                with (
                    patch("pathlib.Path.chmod"),
                    patch("pathlib.Path.exists", return_value=True),
                    patch("pathlib.Path.unlink"),
                ):
                    await backend.execute(
                        mode="apply",
                        playbook="/path/to/playbook.yml",
                        inventory="/path/to/inventory",
                        credentials={
                            "ssh_key": "-----BEGIN RSA PRIVATE KEY-----\n...",
                            "vault_password": "secret123",
                        },
                        run_id="test_run",
                        step_id="test_step",
                    )

                    # Verify credentials were written to temp files
                    assert ssh_file.write.called
                    assert vault_file.write.called

                    # Verify cmdline includes credential flags
                    call_kwargs = mock_run.call_args.kwargs
                    assert "--private-key" in call_kwargs["cmdline"]
                    assert "--vault-password-file" in call_kwargs["cmdline"]

    @pytest.mark.asyncio
    async def test_execute_with_extra_vars(self, backend, mock_runner):
        """Test execution with extra variables."""
        with patch("ansible_runner.run", return_value=mock_runner) as mock_run:
            extra_vars = {"environment": "production", "version": "1.2.3"}

            await backend.execute(
                mode="apply",
                playbook="/path/to/playbook.yml",
                inventory="/path/to/inventory",
                extra_vars=extra_vars,
                run_id="test_run",
                step_id="test_step",
            )

            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["extravars"] == extra_vars

    @pytest.mark.asyncio
    async def test_execute_with_verbosity(self, backend, mock_runner):
        """Test execution with verbosity level."""
        with patch("ansible_runner.run", return_value=mock_runner) as mock_run:
            await backend.execute(
                mode="apply",
                playbook="/path/to/playbook.yml",
                inventory="/path/to/inventory",
                verbosity=3,
                run_id="test_run",
                step_id="test_step",
            )

            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["verbosity"] == 3

    @pytest.mark.asyncio
    async def test_execute_failure_handling(self, backend):
        """Test handling of playbook execution failure."""
        failed_runner = Mock()
        failed_runner.status = "failed"
        failed_runner.rc = 2
        failed_runner.stdout = Mock()
        failed_runner.stdout.read = Mock(return_value="Error output")
        failed_runner.stderr = Mock()
        failed_runner.stderr.read = Mock(return_value="Ansible error details")
        failed_runner.stats = {}
        failed_runner.events = []
        failed_runner.config = Mock()
        failed_runner.config.artifact_dir = "/tmp/test"

        with patch("ansible_runner.run", return_value=failed_runner):
            with pytest.raises(RuntimeError) as exc_info:
                await backend.execute(
                    mode="apply",
                    playbook="/path/to/playbook.yml",
                    inventory="/path/to/inventory",
                    run_id="test_run",
                    step_id="test_step",
                )

            assert "failed (code 2)" in str(exc_info.value)

    def test_build_cmdline_args_check_mode(self, backend):
        """Test building cmdline args for check mode."""
        args = backend._build_cmdline_args(
            mode="check", limit=None, tags=None, skip_tags=None, credentials=None
        )

        assert "--check" in args
        assert "--diff" in args

    def test_build_cmdline_args_with_options(self, backend):
        """Test building cmdline args with various options."""
        args = backend._build_cmdline_args(
            mode="apply",
            limit="web_servers",
            tags=["deploy", "test"],
            skip_tags=["backup"],
            credentials=None,
        )

        assert "--limit" in args
        assert "web_servers" in args
        assert "--tags" in args
        assert "deploy,test" in args
        assert "--skip-tags" in args
        assert "backup" in args

    def test_map_status(self, backend):
        """Test status mapping from ansible_runner to Saz."""
        assert backend._map_status("successful") == "success"
        assert backend._map_status("failed") == "error"
        assert backend._map_status("timeout") == "timeout"

    def test_extract_recap(self, backend, mock_runner):
        """Test recap extraction from runner."""
        recap = backend._extract_recap(mock_runner)

        assert recap["ok"] == 5
        assert recap["changed"] == 2
        assert recap["unreachable"] == 0
        assert recap["failed"] == 0
        assert recap["skipped"] == 1

    def test_extract_recap_multiple_hosts(self, backend):
        """Test recap extraction with multiple hosts."""
        runner = Mock()
        runner.stats = {
            "host1": {
                "ok": 5,
                "changed": 2,
                "unreachable": 0,
                "failed": 0,
                "skipped": 1,
                "rescued": 0,
                "ignored": 0,
            },
            "host2": {
                "ok": 3,
                "changed": 1,
                "unreachable": 0,
                "failed": 0,
                "skipped": 0,
                "rescued": 0,
                "ignored": 0,
            },
        }

        recap = backend._extract_recap(runner)

        # Should aggregate across all hosts
        assert recap["ok"] == 8  # 5 + 3
        assert recap["changed"] == 3  # 2 + 1
        assert recap["skipped"] == 1

    def test_extract_events(self, backend):
        """Test event extraction from runner."""
        runner = Mock()
        runner.events = [
            {
                "event": "playbook_on_start",
                "uuid": "abc123",
                "created": "2025-01-01T00:00:00",
                "stdout": "Starting playbook",
            },
            {
                "event": "runner_on_ok",
                "uuid": "def456",
                "created": "2025-01-01T00:01:00",
                "stdout": "Task completed",
            },
        ]

        events = backend._extract_events(runner)

        assert len(events) == 2
        assert events[0]["event"] == "playbook_on_start"
        assert events[1]["event"] == "runner_on_ok"
