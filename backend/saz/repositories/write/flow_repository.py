"""Flow write repository."""
from datetime import datetime, UTC
from typing import Optional
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session

from saz.db.models import Flow
from saz.repositories.base import BaseRepository


class FlowRepository(BaseRepository[Flow]):
    """Write repository for Flow aggregate."""

    def __init__(self, session: Session):
        super().__init__(session, Flow)

    def create(
        self,
        name: str,
        definition: dict,
        version: Optional[str] = None,
        description: Optional[str] = None
    ) -> Flow:
        """Create new flow."""
        flow = Flow(
            id=str(uuid4()),
            name=name,
            version=version,
            description=description,
            definition=definition,
            created_at=datetime.now(UTC)
        )
        return self.add(flow)

    def get_by_name(self, name: str) -> Optional[Flow]:
        """Get flow by name."""
        stmt = select(Flow).where(Flow.name == name)
        return self.session.scalar(stmt)

    def update_definition(
        self,
        name: str,
        definition: dict,
        version: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[Flow]:
        """Update existing flow definition."""
        flow = self.get_by_name(name)
        if flow:
            flow.definition = definition
            if version is not None:
                flow.version = version
            if description is not None:
                flow.description = description
        return flow