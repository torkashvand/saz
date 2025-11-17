"""Ansible Runner Backend - Executes playbooks using ansible_runner library.

Provides a clean wrapper around ansible_runner for executing Ansible playbooks
with structured event handling, better error reporting, and enhanced artifact capture.
"""

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

            runner = ansible_runner.run(
                playbook=playbook,
                inventory=inventory,
                extravars=final_extra_vars,
                verbosity=verbosity,
                cmdline=" ".join(cmdline_args),
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
                error_msg = f"Ansible playbook failed (code {return_code})"
                if runner.stderr:
                    error_msg += f": {runner.stderr.read()[:500]}"
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

    def _extract_recap(self, runner: Any) -> dict[str, int]:
        """
        Extract recap statistics from ansible_runner.

        ansible_runner provides stats via runner.stats attribute.
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
            # runner.stats is a dict like:
            # {'host1': {'ok': 5, 'changed': 2, 'unreachable': 0, ...}, ...}
            for _host, host_stats in runner.stats.items():
                for key in recap.keys():
                    recap[key] += host_stats.get(key, 0)

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
