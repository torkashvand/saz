"""Flow service - business logic for flow operations."""

import yaml

from saz.db.unit_of_work import UnitOfWork
from saz.repositories.read.dtos import FlowDetailDTO, FlowListItemDTO


class FlowService:
    """Service for flow operations."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    def register(self, yaml_content: str) -> str:
        """Register a new flow from YAML DSL."""
        # Parse YAML
        try:
            dsl = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}") from None

        # Extract metadata
        flow_meta = dsl.get("flow", {})
        name = flow_meta.get("name")
        if not name:
            raise ValueError("Flow name is required")

        version = flow_meta.get("version")
        description = flow_meta.get("description")

        # Check if flow exists
        assert self.uow.flows is not None
        existing = self.uow.flows.get_by_name(name)

        if existing:
            # Update existing flow
            flow = self.uow.flows.update_definition(name, dsl, version, description, yaml_content)
            assert flow is not None
            self.uow.commit()
            return flow.id
        else:
            # Create new flow
            flow = self.uow.flows.create(name, dsl, version, description, yaml_content)
            self.uow.commit()
            return flow.id

    def get(self, flow_id: str) -> FlowDetailDTO | None:
        """Get flow detail."""
        assert self.uow.flow_reads is not None
        return self.uow.flow_reads.detail(flow_id)

    def get_by_name(self, name: str) -> FlowDetailDTO | None:
        """Get flow by name."""
        assert self.uow.flow_reads is not None
        return self.uow.flow_reads.get_by_name(name)

    def list(self, limit: int = 100, offset: int = 0) -> tuple[list[FlowListItemDTO], int]:
        """List flows."""
        assert self.uow.flow_reads is not None
        return self.uow.flow_reads.list(limit, offset)
