"""Unit tests for FlowReadRepository.

The flow read repository is the CQRS read side for flow lookups. It is
called by ``/api/v1/flows`` and ``/api/v1/flows/{id}``. The DTO mapping
must include source_yaml and created_at so the frontend can re-render
the registered YAML and order the list by recency.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from saz.db.models import Flow
from saz.repositories.read.dtos import FlowDetailDTO, FlowListItemDTO
from saz.repositories.read.flow_read_repository import FlowReadRepository


@pytest.fixture
def session(db_engine):
    with Session(db_engine) as s:
        yield s


def _add_flow(
    session: Session,
    *,
    id: str,
    name: str,
    created_at: datetime,
    description: str | None = "test",
    version: str | None = "1.0",
    source_yaml: str | None = "flow: {}",
    definition: dict | None = None,
) -> None:
    session.add(
        Flow(
            id=id,
            name=name,
            description=description,
            version=version,
            definition=definition or {"workflow": {"steps": []}},
            source_yaml=source_yaml,
            created_at=created_at,
        )
    )
    session.commit()


def test_flow_read_repository_list_returns_empty_when_no_flows(session: Session) -> None:
    repo = FlowReadRepository(session)
    items, total = repo.list()
    assert items == []
    assert total == 0


def test_flow_read_repository_list_maps_dtos_in_created_at_desc(session: Session) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    _add_flow(session, id="f-old", name="old", created_at=base)
    _add_flow(session, id="f-mid", name="mid", created_at=base + timedelta(days=1))
    _add_flow(session, id="f-new", name="new", created_at=base + timedelta(days=2))

    repo = FlowReadRepository(session)
    items, total = repo.list()

    assert total == 3
    assert [i.id for i in items] == ["f-new", "f-mid", "f-old"]
    assert all(isinstance(i, FlowListItemDTO) for i in items)
    # DTOs must carry list-page fields the UI needs.
    head = items[0]
    assert head.name == "new"
    assert head.version == "1.0"
    assert head.description == "test"
    assert head.created_at is not None


def test_flow_read_repository_list_respects_limit_and_offset(session: Session) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(5):
        _add_flow(
            session,
            id=f"f-{i}",
            name=f"n-{i}",
            created_at=base + timedelta(seconds=i),
        )

    repo = FlowReadRepository(session)
    page1, total = repo.list(limit=2, offset=0)
    page2, total2 = repo.list(limit=2, offset=2)

    assert total == 5 and total2 == 5
    assert len(page1) == 2
    assert len(page2) == 2
    # Sort is created_at DESC, so the latest two come first.
    assert [i.id for i in page1] == ["f-4", "f-3"]
    assert [i.id for i in page2] == ["f-2", "f-1"]


def test_flow_read_repository_detail_returns_definition_and_source_yaml(
    session: Session,
) -> None:
    definition = {"workflow": {"steps": [{"id": "a", "type": "ai.extract"}]}}
    yaml_src = "flow:\n  name: detail_test\n"
    _add_flow(
        session,
        id="flow-detail-1",
        name="detail_test",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        definition=definition,
        source_yaml=yaml_src,
        version="2.0",
        description="full detail",
    )

    repo = FlowReadRepository(session)
    detail = repo.detail("flow-detail-1")

    assert isinstance(detail, FlowDetailDTO)
    assert detail.id == "flow-detail-1"
    assert detail.name == "detail_test"
    assert detail.version == "2.0"
    assert detail.description == "full detail"
    assert detail.definition == definition
    assert detail.source_yaml == yaml_src


def test_flow_read_repository_detail_returns_none_for_missing(session: Session) -> None:
    repo = FlowReadRepository(session)
    assert repo.detail("does-not-exist") is None


def test_flow_read_repository_get_by_name_returns_match(session: Session) -> None:
    _add_flow(
        session,
        id="named-1",
        name="unique_name",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    repo = FlowReadRepository(session)
    found = repo.get_by_name("unique_name")
    assert found is not None
    assert found.id == "named-1"
    assert found.name == "unique_name"


def test_flow_read_repository_get_by_name_returns_none_when_missing(
    session: Session,
) -> None:
    repo = FlowReadRepository(session)
    assert repo.get_by_name("never-registered") is None
