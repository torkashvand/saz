"""Ansible Tool - Execute Ansible playbooks with safety controls.

Supports:
- check mode (dry-run)
- apply mode (actual execution)
- Credential injection (SSH keys, vault passwords)
- Artifact storage (stdout, events, recap)
- Allowlist policies for playbooks and inventories

Uses ansible_runner library for enhanced execution capabilities.
"""

import json
from pathlib import Path
from typing import Any

import structlog

from .ansible_runner_backend import AnsibleRunnerBackend

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
        runner_artifacts_dir: str = "/tmp/saz/ansible_runner",
    ):
        """
        Initialize Ansible tool.

        Args:
            allowed_playbook_roots: List of allowed playbook directories
            allowed_inventories: List of allowed inventory paths
            artifact_storage_path: Path to store execution artifacts
            runner_artifacts_dir: Path for ansible_runner internal artifacts
        """
        self.allowed_playbook_roots = allowed_playbook_roots or []
        self.allowed_inventories = allowed_inventories or []
        self.artifact_storage_path = Path(artifact_storage_path)
        self.artifact_storage_path.mkdir(parents=True, exist_ok=True)
        self.backend = AnsibleRunnerBackend(runner_artifacts_dir=runner_artifacts_dir)
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

        # Execute via ansible_runner backend
        result = await self.backend.execute(
            mode=mode,
            playbook=playbook,
            inventory=inventory,
            limit=limit,
            tags=tags,
            skip_tags=skip_tags,
            extra_vars=extra_vars,
            credentials=credentials,
            verbosity=verbosity,
            timeout=3600,
            run_id=run_id,
            step_id=step_id,
        )

        # Store enhanced artifacts
        artifact_id = f"{run_id}_{step_id}_ansible"
        artifact_path = self.artifact_storage_path / f"{artifact_id}.json"
        artifact_data = {
            "mode": mode,
            "playbook": playbook,
            "inventory": inventory,
            "stdout": result["stdout"],
            "return_code": result["return_code"],
            "recap": result["recap"],
            "events": result["events"],
            "runner_artifacts_dir": result["runner_artifacts_dir"],
        }
        artifact_path.write_text(json.dumps(artifact_data, indent=2))

        self.logger.info(
            "ansible_execute_complete",
            mode=mode,
            playbook=playbook,
            return_code=result["return_code"],
            recap=result["recap"],
            artifact_id=artifact_id,
        )

        # Return response
        return {
            "status": result["status"],
            "mode": mode,
            "recap": result["recap"],
            "artifact_id": artifact_id,
            "stdout_preview": result["stdout"][:1000],
            "changed": result["changed"],
        }

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
