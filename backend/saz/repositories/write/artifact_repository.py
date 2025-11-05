"""Artifact write repository."""
from datetime import datetime, UTC
from typing import Optional
from uuid import uuid4
from sqlalchemy.orm import Session

from saz.db.models import Artifact
from saz.repositories.base import BaseRepository


class ArtifactRepository(BaseRepository[Artifact]):
    """Write repository for Artifact entity."""

    def __init__(self, session: Session):
        super().__init__(session, Artifact)

    def create(
        self,
        run_id: str,
        name: str,
        blob_ref: str,
        meta: Optional[dict] = None,
        step_id: Optional[str] = None
    ) -> Artifact:
        """Create new artifact."""
        artifact = Artifact(
            id=str(uuid4()),
            run_id=run_id,
            step_id=step_id,
            name=name,
            blob_ref=blob_ref,
            meta=meta or {},
            created_at=datetime.now(UTC)
        )
        return self.add(artifact)