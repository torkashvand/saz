"""Artifact Storage Tool - Store and retrieve workflow artifacts."""
import json
import structlog
from typing import Dict, Any, Optional
from datetime import datetime, UTC
from pathlib import Path
from uuid import uuid4

logger = structlog.get_logger(__name__)


class ArtifactTool:
    """
    MCP-style artifact storage tool.

    Stores workflow outputs, intermediate results, and final artifacts.
    In production, this would use S3/GCS, but starts with filesystem.
    """

    def __init__(self, storage_path: str = "/tmp/saz/artifacts"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.logger = logger.bind(tool="artifact")

    @property
    def store_spec(self) -> Dict[str, Any]:
        """MCP spec for storing artifacts"""
        return {
            "name": "artifact_store",
            "description": "Store workflow output as artifact",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Artifact name (e.g., 'final_report', 'api_response')"
                    },
                    "content": {
                        "type": "object",
                        "description": "Artifact content"
                    },
                    "content_type": {
                        "type": "string",
                        "enum": ["json", "text", "binary"],
                        "default": "json",
                        "description": "Content type"
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Optional metadata",
                        "additionalProperties": True
                    }
                },
                "required": ["name", "content"]
            }
        }

    @property
    def retrieve_spec(self) -> Dict[str, Any]:
        """MCP spec for retrieving artifacts"""
        return {
            "name": "artifact_retrieve",
            "description": "Retrieve stored artifact",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "artifact_id": {
                        "type": "string",
                        "description": "Artifact ID from store operation"
                    }
                },
                "required": ["artifact_id"]
            }
        }

    async def store(
        self,
        name: str,
        content: Any,
        content_type: str = "json",
        metadata: Optional[Dict[str, Any]] = None,
        run_id: str = "",
        step_id: str = ""
    ) -> Dict[str, Any]:
        """
        Store artifact.

        Args:
            name: Artifact name
            content: Artifact content
            content_type: Type (json, text, binary)
            metadata: Optional metadata
            run_id: Associated run ID
            step_id: Associated step ID

        Returns:
            Dict with artifact_id and storage metadata
        """
        artifact_id = str(uuid4())
        timestamp = datetime.now(UTC)

        artifact_record = {
            "artifact_id": artifact_id,
            "name": name,
            "content_type": content_type,
            "content": content,
            "metadata": metadata or {},
            "run_id": run_id,
            "step_id": step_id,
            "created_at": timestamp.isoformat()
        }

        # Store to filesystem
        artifact_file = self.storage_path / f"{artifact_id}.json"
        with open(artifact_file, 'w') as f:
            json.dump(artifact_record, f, indent=2, default=str)

        self.logger.info(
            "artifact_stored",
            artifact_id=artifact_id,
            name=name,
            content_type=content_type,
            run_id=run_id,
            step_id=step_id,
            file_path=str(artifact_file)
        )

        return {
            "artifact_id": artifact_id,
            "name": name,
            "status": "stored",
            "storage_path": str(artifact_file),
            "created_at": timestamp.isoformat()
        }

    async def retrieve(
        self,
        artifact_id: str
    ) -> Dict[str, Any]:
        """
        Retrieve artifact by ID.

        Args:
            artifact_id: Artifact ID

        Returns:
            Artifact record with content

        Raises:
            FileNotFoundError: If artifact not found
        """
        artifact_file = self.storage_path / f"{artifact_id}.json"

        if not artifact_file.exists():
            self.logger.error(
                "artifact_not_found",
                artifact_id=artifact_id
            )
            raise FileNotFoundError(f"Artifact {artifact_id} not found")

        with open(artifact_file, 'r') as f:
            artifact_record = json.load(f)

        self.logger.info(
            "artifact_retrieved",
            artifact_id=artifact_id,
            name=artifact_record.get("name"),
            run_id=artifact_record.get("run_id")
        )

        return artifact_record

    async def list_artifacts(
        self,
        run_id: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        """
        List all artifacts, optionally filtered by run_id.

        Args:
            run_id: Filter by run ID

        Returns:
            List of artifact metadata (without content)
        """
        artifacts = []

        for artifact_file in self.storage_path.glob("*.json"):
            try:
                with open(artifact_file, 'r') as f:
                    artifact_record = json.load(f)

                # Filter by run_id if specified
                if run_id and artifact_record.get("run_id") != run_id:
                    continue

                # Return metadata only
                artifacts.append({
                    "artifact_id": artifact_record["artifact_id"],
                    "name": artifact_record["name"],
                    "content_type": artifact_record["content_type"],
                    "run_id": artifact_record.get("run_id"),
                    "step_id": artifact_record.get("step_id"),
                    "created_at": artifact_record["created_at"]
                })
            except Exception as e:
                self.logger.warning(
                    "artifact_list_error",
                    file=str(artifact_file),
                    error=str(e)
                )
                continue

        self.logger.info(
            "artifacts_listed",
            count=len(artifacts),
            run_id=run_id
        )

        return artifacts
