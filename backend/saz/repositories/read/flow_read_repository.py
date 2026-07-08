"""Flow read repository for CQRS queries."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from saz.db.models import Flow
from saz.repositories.read.dtos import FlowDetailDTO, FlowListItemDTO


class FlowReadRepository:
    """Read repository for Flow queries (CQRS)."""

    def __init__(self, session: Session):
        self.session = session

    def list(self, limit: int = 100, offset: int = 0) -> tuple[list[FlowListItemDTO], int]:
        """List flows with pagination."""
        # Count total
        count_stmt = select(func.count()).select_from(Flow)
        total = self.session.scalar(count_stmt) or 0

        # Query with pagination
        stmt = select(Flow).order_by(Flow.created_at.desc()).limit(limit).offset(offset)
        flows = self.session.scalars(stmt).all()

        # Map to DTOs. planner_mode lives in the stored definition, not as a
        # column (mirrors the detail endpoint's derivation).
        items = [
            FlowListItemDTO(
                id=flow.id,
                name=flow.name,
                version=flow.version,
                description=flow.description,
                planner_mode=(flow.definition.get("workflow") or {}).get(
                    "planner_mode", "deterministic"
                ),
                created_at=flow.created_at,
            )
            for flow in flows
        ]

        return items, total

    def detail(self, flow_id: str) -> FlowDetailDTO | None:
        """Get flow detail."""
        stmt = select(Flow).where(Flow.id == flow_id)
        flow = self.session.scalar(stmt)

        if not flow:
            return None

        return FlowDetailDTO(
            id=flow.id,
            name=flow.name,
            version=flow.version,
            description=flow.description,
            definition=flow.definition,
            source_yaml=flow.source_yaml,
            created_at=flow.created_at,
        )

    def get_by_name(self, name: str) -> FlowDetailDTO | None:
        """Get flow by name."""
        stmt = select(Flow).where(Flow.name == name)
        flow = self.session.scalar(stmt)

        if not flow:
            return None

        return FlowDetailDTO(
            id=flow.id,
            name=flow.name,
            version=flow.version,
            description=flow.description,
            definition=flow.definition,
            source_yaml=flow.source_yaml,
            created_at=flow.created_at,
        )
