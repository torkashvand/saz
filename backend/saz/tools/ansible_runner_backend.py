"""Ansible Runner Backend - Executes playbooks using ansible_runner library.

Provides a clean wrapper around ansible_runner for executing Ansible playbooks
with structured event handling, better error reporting, and enhanced artifact capture.
"""

import shlex
import tempfile
from pathlib import Path
from typing import Any

import ansible_runner
import structlog

logger = structlog.get_logger(__name__)


class AnsibleRunnerBackend:
    """
    Backend for executing Ansible playbooks via ansible_runner library.

    Features:
    - Structured event capture
    - Better error handling than raw subprocess
    - Native recap parsing
    - Event streaming support (future)
    """

    def __init__(
        self,
        runner_artifacts_dir: str = "/tmp/saz/ansible_runner",
    ):
        """
        Initialize Ansible Runner backend.

        Args:
            runner_artifacts_dir: Directory for ansible_runner's internal artifacts
        """
        self.runner_artifacts_dir = Path(runner_artifacts_dir)
        self.runner_artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger.bind(backend="ansible_runner")

    async def execute(
        self,
        mode: str,
        playbook: str,
        inventory: str,
        limit: str | None = None,
        tags: list[str] | None = None,
        skip_tags: list[str] | None = None,
        extra_vars: dict[str, Any] | None = None,
        credentials: dict[str, str] | None = None,
        verbosity: int = 0,
        timeout: int = 3600,
        run_id: str = "",
        step_id: str = "",
    ) -> dict[str, Any]:
        """
        Execute Ansible playbook using ansible_runner.

        Args:
            mode: "check" or "apply"
            playbook: Path to playbook file
            inventory: Path to inventory file
            limit: Limit to specific hosts
            tags: Tags to execute
            skip_tags: Tags to skip
            extra_vars: Extra variables
            credentials: SSH key, vault password
            verbosity: Ansible verbosity (0-4)
            timeout: Execution timeout in seconds
            run_id: Current run ID
            step_id: Current step ID

        Returns:
            Dict with status, recap, events, artifact info
        """
        self.logger.info(
            "ansible_runner_execute_start",
            mode=mode,
            playbook=playbook,
            inventory=inventory,
            run_id=run_id,
            step_id=step_id,
        )

        # Build cmdline arguments
        cmdline_args = self._build_cmdline_args(
            mode=mode,
            limit=limit,
            tags=tags,
            skip_tags=skip_tags,
            credentials=credentials,
        )

        # Prepare extra vars
        final_extra_vars = extra_vars or {}

        # Inject credentials via temp files
        ssh_key_file = None
        vault_pass_file = None

        try:
            if credentials:
                if "ssh_key" in credentials:
                    ssh_key_file = tempfile.NamedTemporaryFile(
                        mode='w', delete=False, suffix='_id_rsa'
                    )
                    ssh_key_file.write(credentials["ssh_key"])
                    ssh_key_file.close()
                    Path(ssh_key_file.name).chmod(0o600)
                    cmdline_args.extend(["--private-key", ssh_key_file.name])

                if "vault_password" in credentials:
                    vault_pass_file = tempfile.NamedTemporaryFile(
                        mode='w', delete=False, suffix='_vault'
                    )
                    vault_pass_file.write(credentials["vault_password"])
                    vault_pass_file.close()
                    Path(vault_pass_file.name).chmod(0o600)
                    cmdline_args.extend(["--vault-password-file", vault_pass_file.name])

            # Execute via ansible_runner
            self.logger.info(
                "ansible_runner_invoke",
                playbook=playbook,
                cmdline_preview=" ".join(cmdline_args[:10]),
            )

            # Use shlex.join so cmdline args with shell-special characters
            # (spaces, quotes, &, *, etc.) survive ansible_runner's internal
            # shell splitting as a single argument. Plain " ".join breaks the
            # moment a user-supplied --limit pattern or credential path
            # contains anything outside [\w@%+=:,./-].
            runner = ansible_runner.run(
                playbook=playbook,
                inventory=inventory,
                extravars=final_extra_vars,
                verbosity=verbosity,
                cmdline=shlex.join(cmdline_args),
                private_data_dir=str(self.runner_artifacts_dir),
                quiet=False,
                json_mode=False,
                timeout=timeout,
            )

            # Extract results
            status = self._map_status(runner.status)
            return_code = runner.rc
            stdout = runner.stdout.read() if runner.stdout else ""

            # Extract structured recap
            recap = self._extract_recap(runner)

            # Gather events for artifact storage
            events = self._extract_events(runner)

            self.logger.info(
                "ansible_runner_execute_complete",
                status=status,
                return_code=return_code,
                recap=recap,
                event_count=len(events),
            )

            # Determine success
            if return_code != 0:
                stderr_text = ""
                if runner.stderr:
                    stderr_text = runner.stderr.read()[:500]

                # Exit code 127 from ansible_runner overwhelmingly means
                # the ansible-playbook binary itself is not on PATH (or
                # ansible-runner can't find it). The raw "code 127" with
                # empty stderr is unactionable; surface what to install.
                if return_code == 127:
                    error_msg = (
                        "Ansible playbook failed (code 127): the "
                        "'ansible-playbook' binary was not found on PATH. "
                        "Install Ansible (pip install 'ansible-core' "
                        "or your distro's ansible package) and make sure "
                        "'ansible-playbook' resolves, then retry."
                    )
                else:
                    error_msg = f"Ansible playbook failed (code {return_code})"
                    if stderr_text:
                        error_msg += f": {stderr_text}"
                raise RuntimeError(error_msg)

            return {
                "status": status,
                "mode": mode,
                "recap": recap,
                "return_code": return_code,
                "stdout": stdout,
                "events": events,
                "runner_artifacts_dir": str(runner.config.artifact_dir),
                "changed": recap.get("changed", 0) > 0,
            }

        finally:
            # Clean up temp credential files
            if ssh_key_file and Path(ssh_key_file.name).exists():
                Path(ssh_key_file.name).unlink()
            if vault_pass_file and Path(vault_pass_file.name).exists():
                Path(vault_pass_file.name).unlink()

    def _build_cmdline_args(
        self,
        mode: str,
        limit: str | None,
        tags: list[str] | None,
        skip_tags: list[str] | None,
        credentials: dict[str, str] | None,
    ) -> list[str]:
        """Build ansible-playbook cmdline arguments."""
        args: list[str] = []

        # Add check mode flags
        if mode == "check":
            args.extend(["--check", "--diff"])

        # Add limit
        if limit:
            args.extend(["--limit", limit])

        # Add tags
        if tags:
            args.extend(["--tags", ",".join(tags)])

        # Add skip tags
        if skip_tags:
            args.extend(["--skip-tags", ",".join(skip_tags)])

        return args

    def _map_status(self, runner_status: str) -> str:
        """Map ansible_runner status to Saz status."""
        if runner_status == "successful":
            return "success"
        elif runner_status == "failed":
            return "error"
        else:
            return runner_status  # timeout, canceled, etc.

    # Mapping from ansible_runner.Runner.stats keys to Saz recap keys.
    # ansible_runner emits 'dark' for unreachable and 'failures' for failed;
    # the rest line up by name. 'processed' is intentionally not surfaced —
    # the PLAY RECAP line operators are used to seeing doesn't include it.
    _RUNNER_TO_SAZ_RECAP_KEYS: dict[str, str] = {
        "ok": "ok",
        "changed": "changed",
        "dark": "unreachable",
        "failures": "failed",
        "skipped": "skipped",
        "rescued": "rescued",
        "ignored": "ignored",
    }

    def _extract_recap(self, runner: Any) -> dict[str, int]:
        """
        Extract recap statistics from ansible_runner.

        ansible_runner.Runner.stats is keyed by STAT name then host:
            {'ok': {'localhost': 3}, 'changed': {'localhost': 2}, 'dark': {},
             'failures': {}, 'skipped': {}, 'ignored': {}, 'rescued': {},
             'processed': {'localhost': 1}}
        (See ansible_runner/runner.py::Runner.stats.) Saz uses the more
        common Ansible CLI names — 'unreachable' instead of 'dark',
        'failed' instead of 'failures' — so we both flip the axis and
        translate the keys.
        """
        recap: dict[str, int] = {
            "ok": 0,
            "changed": 0,
            "unreachable": 0,
            "failed": 0,
            "skipped": 0,
            "rescued": 0,
            "ignored": 0,
        }

        if hasattr(runner, "stats") and runner.stats:
            for runner_key, saz_key in self._RUNNER_TO_SAZ_RECAP_KEYS.items():
                host_counts = runner.stats.get(runner_key) or {}
                # Sum across all hosts in the play.
                recap[saz_key] = sum(int(v) for v in host_counts.values())

        return recap

    def _extract_events(self, runner: Any) -> list[dict[str, Any]]:
        """
        Extract event log from ansible_runner.

        ansible_runner stores events in its artifact directory.
        We'll return a simplified version for artifact storage.
        """
        events: list[dict[str, Any]] = []

        if hasattr(runner, "events"):
            for event in runner.events:
                # Simplify event data for storage
                events.append(
                    {
                        "event": event.get("event", "unknown"),
                        "uuid": event.get("uuid", ""),
                        "created": event.get("created", ""),
                        "stdout": event.get("stdout", ""),
                    }
                )

        return events
