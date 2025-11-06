"""Ansible Tool - Execute Ansible playbooks with safety controls.

Supports:
- check mode (dry-run)
- apply mode (actual execution)
- Credential injection (SSH keys, vault passwords)
- Artifact storage (stdout, events, recap)
- Allowlist policies for playbooks and inventories
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class AnsibleTool:
    """
    Ansible playbook executor with safety controls.

    Features:
    - Check/apply modes
    - Credential injection
    - Event streaming capture
    - Policy enforcement (allowlists)
    """

    def __init__(
        self,
        allowed_playbook_roots: list[str] | None = None,
        allowed_inventories: list[str] | None = None,
        artifact_storage_path: str = "/tmp/saz/ansible_artifacts",
    ):
        """
        Initialize Ansible tool.

        Args:
            allowed_playbook_roots: List of allowed playbook directories
            allowed_inventories: List of allowed inventory paths
            artifact_storage_path: Path to store execution artifacts
        """
        self.allowed_playbook_roots = allowed_playbook_roots or []
        self.allowed_inventories = allowed_inventories or []
        self.artifact_storage_path = Path(artifact_storage_path)
        self.artifact_storage_path.mkdir(parents=True, exist_ok=True)
        self.logger = logger.bind(tool="ansible")

    @property
    def spec(self) -> dict[str, Any]:
        """MCP-style tool specification."""
        return {
            "name": "ansible_run",
            "description": (
                "Execute Ansible playbooks (check or apply mode) with credential injection"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["check", "apply"],
                        "description": "Execution mode: check (dry-run) or apply (actual)",
                    },
                    "playbook": {
                        "type": "string",
                        "description": "Path to playbook file or collection name",
                    },
                    "inventory": {
                        "type": "string",
                        "description": "Path to inventory file or dynamic inventory",
                    },
                    "limit": {
                        "type": "string",
                        "description": "Limit execution to specific hosts (optional)",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags to execute (optional)",
                    },
                    "skip_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags to skip (optional)",
                    },
                    "extra_vars": {
                        "type": "object",
                        "description": "Extra variables to pass to playbook",
                    },
                    "credentials": {
                        "type": "object",
                        "properties": {
                            "ssh_key": {
                                "type": "string",
                                "description": "SSH private key (injected)",
                            },
                            "vault_password": {
                                "type": "string",
                                "description": "Ansible vault password",
                            },
                        },
                    },
                    "verbosity": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 4,
                        "description": "Ansible verbosity level (0-4)",
                    },
                },
                "required": ["mode", "playbook", "inventory"],
            },
        }

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
        run_id: str = "",
        step_id: str = "",
    ) -> dict[str, Any]:
        """
        Execute Ansible playbook.

        Args:
            mode: check or apply
            playbook: Playbook path
            inventory: Inventory path
            limit: Host limit (optional)
            tags: Tags to run (optional)
            skip_tags: Tags to skip (optional)
            extra_vars: Extra variables
            credentials: SSH key, vault password
            verbosity: Verbosity level (0-4)
            run_id: Current run ID
            step_id: Current step ID

        Returns:
            Dict with stdout, events, recap, artifacts
        """
        self.logger.info(
            "ansible_execute_start",
            mode=mode,
            playbook=playbook,
            inventory=inventory,
            run_id=run_id,
            step_id=step_id,
        )

        # Policy check: validate playbook and inventory paths
        if not self._is_allowed_playbook(playbook):
            raise ValueError(
                f"Playbook '{playbook}' not in allowed roots: {self.allowed_playbook_roots}"
            )

        if not self._is_allowed_inventory(inventory):
            raise ValueError(
                f"Inventory '{inventory}' not in allowed inventories: {self.allowed_inventories}"
            )

        # Build ansible-playbook command
        cmd = ["ansible-playbook", playbook, "-i", inventory]

        # Add mode flag
        if mode == "check":
            cmd.extend(["--check", "--diff"])

        # Add limit
        if limit:
            cmd.extend(["--limit", limit])

        # Add tags
        if tags:
            cmd.extend(["--tags", ",".join(tags)])
        if skip_tags:
            cmd.extend(["--skip-tags", ",".join(skip_tags)])

        # Add extra vars
        if extra_vars:
            cmd.extend(["--extra-vars", json.dumps(extra_vars)])

        # Add verbosity
        if verbosity > 0:
            cmd.append(f"-{'v' * verbosity}")

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
                    cmd.extend(["--private-key", ssh_key_file.name])

                if "vault_password" in credentials:
                    vault_pass_file = tempfile.NamedTemporaryFile(
                        mode='w', delete=False, suffix='_vault'
                    )
                    vault_pass_file.write(credentials["vault_password"])
                    vault_pass_file.close()
                    Path(vault_pass_file.name).chmod(0o600)
                    cmd.extend(["--vault-password-file", vault_pass_file.name])

            # Execute playbook
            self.logger.info(
                "ansible_command", cmd=" ".join(cmd[:6]) + " ..."
            )  # Don't log full command

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour max
            )

            stdout = result.stdout
            stderr = result.stderr
            return_code = result.returncode

            # Parse recap from stdout
            recap = self._parse_recap(stdout)

            # Store artifacts
            artifact_id = f"{run_id}_{step_id}_ansible"
            artifact_path = self.artifact_storage_path / f"{artifact_id}.json"
            artifact_data = {
                "mode": mode,
                "playbook": playbook,
                "inventory": inventory,
                "stdout": stdout,
                "stderr": stderr,
                "return_code": return_code,
                "recap": recap,
            }
            artifact_path.write_text(json.dumps(artifact_data, indent=2))

            self.logger.info(
                "ansible_execute_complete",
                mode=mode,
                playbook=playbook,
                return_code=return_code,
                recap=recap,
                artifact_id=artifact_id,
            )

            # Determine success based on return code
            if return_code != 0:
                raise RuntimeError(f"Ansible playbook failed (code {return_code}): {stderr[:500]}")

            return {
                "status": "success",
                "mode": mode,
                "recap": recap,
                "artifact_id": artifact_id,
                "stdout_preview": stdout[:1000],
                "changed": recap.get("changed", 0) > 0,
            }

        finally:
            # Clean up temp files
            if ssh_key_file and Path(ssh_key_file.name).exists():
                Path(ssh_key_file.name).unlink()
            if vault_pass_file and Path(vault_pass_file.name).exists():
                Path(vault_pass_file.name).unlink()

    def _is_allowed_playbook(self, playbook: str) -> bool:
        """Check if playbook is in allowed roots."""
        if not self.allowed_playbook_roots:
            return True  # No restrictions

        playbook_path = Path(playbook).resolve()
        for allowed_root in self.allowed_playbook_roots:
            root_path = Path(allowed_root).resolve()
            try:
                playbook_path.relative_to(root_path)
                return True
            except ValueError:
                continue
        return False

    def _is_allowed_inventory(self, inventory: str) -> bool:
        """Check if inventory is in allowed list."""
        if not self.allowed_inventories:
            return True  # No restrictions

        inventory_path = Path(inventory).resolve()
        for allowed in self.allowed_inventories:
            allowed_path = Path(allowed).resolve()
            if inventory_path == allowed_path:
                return True
        return False

    def _parse_recap(self, stdout: str) -> dict[str, int]:
        """
        Parse Ansible recap from stdout.

        Example:
            PLAY RECAP *********************************************************************
            host1                      : ok=5    changed=2    unreachable=0    failed=0
                                         skipped=1    rescued=0    ignored=0
        """
        recap = {
            "ok": 0,
            "changed": 0,
            "unreachable": 0,
            "failed": 0,
            "skipped": 0,
            "rescued": 0,
            "ignored": 0,
        }

        lines = stdout.split("\n")
        in_recap = False

        for line in lines:
            if "PLAY RECAP" in line:
                in_recap = True
                continue

            if in_recap and ":" in line:
                # Parse recap line
                parts = line.split(":")
                if len(parts) >= 2:
                    stats_str = parts[1]
                    for key in recap.keys():
                        if key + "=" in stats_str:
                            try:
                                val_str = stats_str.split(key + "=")[1].split()[0]
                                recap[key] += int(val_str)
                            except (IndexError, ValueError):
                                pass

        return recap
