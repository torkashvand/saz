"""API contract tests for the health endpoint.

Health is the readiness probe for the platform — operators rely on the
status code to gate deployments. The endpoint must:

  * report 200 with ``status=healthy`` and ``database=connected`` when the
    UnitOfWork can SELECT 1, and
  * report 503 with ``status=unhealthy`` when the database probe raises.
"""

from sqlalchemy.exc import OperationalError

from saz.api import app
from saz.db.dependencies import get_uow


def test_root_endpoint_returns_service_contract(app_client) -> None:
    """The unauthenticated root must advertise the service name and docs link."""
    resp = app_client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "Saz Agentic Workflow Engine"
    assert body["status"] == "running"
    assert body["version"]
    assert body["docs"] == "/docs"


def test_health_endpoint_returns_ok_when_database_responsive(app_client) -> None:
    resp = app_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "healthy", "database": "connected"}


def test_health_endpoint_returns_503_when_database_probe_fails(app_client) -> None:
    """When the underlying SELECT 1 raises, the endpoint must report unhealthy
    with a non-2xx status — load balancers depend on this to drain traffic.

    Overrides ``get_uow`` on top of the existing app_client override so the
    sync-scheduler fixture stays intact for the rest of the suite.
    """

    class _FailingUoW:
        def execute(self, _query: str) -> None:
            raise OperationalError("SELECT 1", params={}, orig=RuntimeError("connection refused"))

    previous = app.dependency_overrides.get(get_uow)

    def _override():
        yield _FailingUoW()

    app.dependency_overrides[get_uow] = _override
    try:
        resp = app_client.get("/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "unhealthy"
        assert body["database"] == "disconnected"
        assert "error" in body
        assert body["error"]
    finally:
        if previous is not None:
            app.dependency_overrides[get_uow] = previous
        else:
            app.dependency_overrides.pop(get_uow, None)
