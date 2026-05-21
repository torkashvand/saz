"""Flow write repository."""

from datetime import UTC, datetime
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
        created_by_user_id: str,
        version: str | None = None,
        description: str | None = None,
        source_yaml: str | None = None,
    ) -> Flow:
        """Create new flow."""
        flow = Flow(
            id=str(uuid4()),
            name=name,
            version=version,
            description=description,
            definition=definition,
            source_yaml=source_yaml,
            created_at=datetime.now(UTC),
            created_by_user_id=created_by_user_id,
        )
        return self.add(flow)

    def get_by_name(self, name: str) -> Flow | None:
        """Get flow by name."""
        stmt = select(Flow).where(Flow.name == name)
        return self.session.scalar(stmt)

    def update_definition(
        self,
        name: str,
        definition: dict,
        version: str | None = None,
        description: str | None = None,
        source_yaml: str | None = None,
    ) -> Flow | None:
        """Update existing flow definition."""
        flow = self.get_by_name(name)
        if flow:
            flow.definition = definition
            if version is not None:
                flow.version = version
            if description is not None:
                flow.description = description
            if source_yaml is not None:
                flow.source_yaml = source_yaml
        return flow

    def get_by_id(self, flow_id: str) -> Flow | None:
        """Get flow by ID."""
        stmt = select(Flow).where(Flow.id == flow_id)
        return self.session.scalar(stmt)

    def update_by_id(
        self,
        flow_id: str,
        new_name: str,
        definition: dict,
        version: str | None = None,
        description: str | None = None,
        source_yaml: str | None = None,
    ) -> Flow | None:
        """Update existing flow row by ID. Lets a flow be renamed safely."""
        flow = self.get_by_id(flow_id)
        if flow:
            flow.name = new_name
            flow.definition = definition
            if version is not None:
                flow.version = version
            if description is not None:
                flow.description = description
            if source_yaml is not None:
                flow.source_yaml = source_yaml
        return flow
