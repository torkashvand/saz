"""Tests for Ansible Runner Backend."""

import shlex
from unittest.mock import Mock, patch

import pytest

from saz.tools.ansible_runner_backend import AnsibleRunnerBackend


@pytest.fixture
def backend():
    """Create an AnsibleRunnerBackend instance for testing."""
    return AnsibleRunnerBackend(runner_artifacts_dir="/tmp/test_ansible_runner")


@pytest.fixture
def mock_runner():
    """Create a mock ansible_runner.Runner object.

    Shape mirrors the real ansible_runner.Runner.stats property:
    keyed by stat name → {host: count}, with ansible_runner's own names
    ('dark' = unreachable, 'failures' = failed). See
    ansible_runner/runner.py::Runner.stats.
    """
    runner = Mock()
    runner.status = "successful"
    runner.rc = 0
    runner.stdout = Mock()
    runner.stdout.read = Mock(return_value="PLAY RECAP\nhost1: ok=5 changed=2 failed=0")
    runner.stderr = None
    runner.stats = {
        "ok": {"host1": 5},
        "changed": {"host1": 2},
        "dark": {},
        "failures": {},
        "skipped": {"host1": 1},
        "rescued": {},
        "ignored": {},
        "processed": {"host1": 1},
    }
    runner.events = []
    runner.config = Mock()
    runner.config.artifact_dir = "/tmp/test_ansible_runner/artifacts"
    return runner


@pytest.mark.asyncio
async def test_execute_check_mode(backend, mock_runner):
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
async def test_execute_raises_actionable_error_when_ansible_binary_missing(backend):
    """ansible_runner returns exit code 127 when the ansible-playbook
    binary is not on PATH. The bare 'code 127' message with empty
    stderr is unactionable for operators; the wrapper must surface
    *what to install* in the RuntimeError."""
    failing_runner = Mock()
    failing_runner.status = "failed"
    failing_runner.rc = 127
    failing_runner.stdout = Mock(read=Mock(return_value=""))
    failing_runner.stderr = Mock(read=Mock(return_value=""))
    failing_runner.stats = {}
    failing_runner.events = []
    failing_runner.config = Mock(artifact_dir="/tmp/test/artifacts")

    with patch("ansible_runner.run", return_value=failing_runner):
        with pytest.raises(RuntimeError) as exc_info:
            await backend.execute(
                mode="check",
                playbook="/path/to/playbook.yml",
                inventory="/path/to/inventory",
                run_id="r",
                step_id="s",
            )
    msg = str(exc_info.value).lower()
    # Must call out the missing binary explicitly so an operator can act.
    assert "127" in str(exc_info.value)
    assert "ansible-playbook" in msg
    assert "path" in msg
    # And must point at how to fix it.
    assert "install" in msg


@pytest.mark.asyncio
async def test_execute_preserves_real_stderr_for_non_127_failures(backend):
    """For other non-zero exit codes, the existing behaviour (forward
    the first 500 chars of stderr) must stay so playbook-level errors
    remain actionable."""
    failing_runner = Mock()
    failing_runner.status = "failed"
    failing_runner.rc = 2
    failing_runner.stdout = Mock(read=Mock(return_value=""))
    failing_runner.stderr = Mock(read=Mock(return_value="syntax error in playbook"))
    failing_runner.stats = {}
    failing_runner.events = []
    failing_runner.config = Mock(artifact_dir="/tmp/test/artifacts")

    with patch("ansible_runner.run", return_value=failing_runner):
        with pytest.raises(RuntimeError) as exc_info:
            await backend.execute(
                mode="apply",
                playbook="/path/to/playbook.yml",
                inventory="/path/to/inventory",
                run_id="r",
                step_id="s",
            )
    assert "code 2" in str(exc_info.value)
    assert "syntax error in playbook" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_apply_mode(backend, mock_runner):
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
async def test_execute_with_limit(backend, mock_runner):
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
async def test_execute_shell_escapes_limit_with_special_chars(backend, mock_runner):
    """Limit values containing spaces, quotes, commas, or other shell-special
    characters must be passed to ansible-playbook as a SINGLE argument.

    Regression: a literal-paste like  '"localhost", "web*", "edge:&prod"'  was
    leaking through " ".join() unescaped, so ansible-playbook split it into
    several positional args and rejected the trailing playbook path with
    "unrecognized arguments: <playbook>".
    """
    weird_limit = ' "localhost", "web*", "edge:&prod"'
    with patch("ansible_runner.run", return_value=mock_runner) as mock_run:
        await backend.execute(
            mode="check",
            playbook="/path/to/playbook.yml",
            inventory="/path/to/inventory",
            limit=weird_limit,
            run_id="test_run",
            step_id="test_step",
        )

        cmdline = mock_run.call_args.kwargs["cmdline"]
        # shlex.split must round-trip back to the same logical args — i.e.
        # the weird limit string survives as one arg, not several.
        split = shlex.split(cmdline)
        assert "--limit" in split
        assert split[split.index("--limit") + 1] == weird_limit


@pytest.mark.asyncio
async def test_execute_shell_escapes_safe_limit_unchanged(backend, mock_runner):
    """Safe identifiers must remain unquoted so existing operator habits
    (and existing cmdline-string assertions) still hold."""
    with patch("ansible_runner.run", return_value=mock_runner) as mock_run:
        await backend.execute(
            mode="apply",
            playbook="/path/to/playbook.yml",
            inventory="/path/to/inventory",
            limit="web_servers",
            run_id="test_run",
            step_id="test_step",
        )
        cmdline = mock_run.call_args.kwargs["cmdline"]
        # No spurious quoting for shell-safe values.
        assert "--limit web_servers" in cmdline


@pytest.mark.asyncio
async def test_execute_with_tags(backend, mock_runner):
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
async def test_execute_with_skip_tags(backend, mock_runner):
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
async def test_execute_with_credentials(backend, mock_runner):
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
async def test_execute_with_extra_vars(backend, mock_runner):
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
async def test_execute_with_verbosity(backend, mock_runner):
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
async def test_execute_failure_handling(backend):
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


def test_build_cmdline_args_check_mode(backend):
    """Test building cmdline args for check mode."""
    args = backend._build_cmdline_args(
        mode="check", limit=None, tags=None, skip_tags=None, credentials=None
    )

    assert "--check" in args
    assert "--diff" in args


def test_build_cmdline_args_with_options(backend):
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


def test_map_status(backend):
    """Test status mapping from ansible_runner to Saz."""
    assert backend._map_status("successful") == "success"
    assert backend._map_status("failed") == "error"
    assert backend._map_status("timeout") == "timeout"


def test_extract_recap(backend, mock_runner):
    """Test recap extraction from runner."""
    recap = backend._extract_recap(mock_runner)

    assert recap["ok"] == 5
    assert recap["changed"] == 2
    assert recap["unreachable"] == 0
    assert recap["failed"] == 0
    assert recap["skipped"] == 1


def test_extract_recap_multiple_hosts(backend):
    """Test recap extraction with multiple hosts."""
    runner = Mock()
    # ansible_runner format: keyed by stat name, then host → count.
    runner.stats = {
        "ok": {"host1": 5, "host2": 3},
        "changed": {"host1": 2, "host2": 1},
        "dark": {},
        "failures": {},
        "skipped": {"host1": 1},
        "rescued": {},
        "ignored": {},
        "processed": {"host1": 1, "host2": 1},
    }

    recap = backend._extract_recap(runner)

    # Should aggregate across all hosts
    assert recap["ok"] == 8  # 5 + 3
    assert recap["changed"] == 3  # 2 + 1
    assert recap["skipped"] == 1


def test_extract_recap_translates_dark_and_failures(backend):
    """Regression: ansible_runner emits 'dark' for unreachable hosts and
    'failures' for failed hosts. Saz exposes 'unreachable' and 'failed' in
    its recap. The translation must happen — otherwise a real production run
    silently reports unreachable=0/failed=0 while hosts are actually down,
    and 'changed' downstream consumers (the post-execution critic, the UI)
    think nothing happened."""
    runner = Mock()
    runner.stats = {
        "ok": {"host1": 1},
        "changed": {"host1": 1},
        "dark": {"host2": 1, "host3": 1},  # unreachable
        "failures": {"host4": 1},  # failed
        "skipped": {},
        "rescued": {},
        "ignored": {},
        "processed": {"host1": 1},
    }

    recap = backend._extract_recap(runner)

    assert recap["unreachable"] == 2, "two 'dark' hosts must surface as unreachable=2"
    assert recap["failed"] == 1, "one 'failures' host must surface as failed=1"
    assert recap["ok"] == 1
    assert recap["changed"] == 1


def test_extract_recap_returns_zeros_when_stats_missing(backend):
    """If ansible_runner didn't emit a playbook_on_stats event (e.g. the run
    exited before stats were tallied), runner.stats is None. The recap must
    still return a fully-populated zero dict rather than crashing."""
    runner = Mock()
    runner.stats = None
    recap = backend._extract_recap(runner)
    for key in ("ok", "changed", "unreachable", "failed", "skipped", "rescued", "ignored"):
        assert recap[key] == 0


def test_extract_events(backend):
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
