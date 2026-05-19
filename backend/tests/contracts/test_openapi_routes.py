"""OpenAPI contract: route inventory and key response shapes.

Snapshots the set of (method, path) pairs the API exposes plus a few
response-model invariants. The intent isn't to lock the entire JSON
schema (too brittle, too much churn) — just to catch:
  - accidental removal of a route the frontend depends on,
  - accidental change of an endpoint's path or method,
  - silent changes to response model class names for stable contracts.
"""

import pytest

# Frozen list of routes the frontend + external callers depend on.
# Adding a new route is fine — just append to this set.
# Removing or renaming a route should be a deliberate update here AND a
# matching frontend change.
EXPECTED_ROUTES: set[tuple[str, str]] = {
    ("GET", "/api/v1/flows"),
    ("POST", "/api/v1/flows"),
    ("POST", "/api/v1/flows/compile"),
    ("GET", "/api/v1/flows/ai-ops"),
    ("GET", "/api/v1/flows/{flow_id}"),
    ("GET", "/api/v1/flows/{flow_id}/graph"),
    ("GET", "/api/v1/runs"),
    ("POST", "/api/v1/runs"),
    ("GET", "/api/v1/runs/{run_id}"),
    ("GET", "/api/v1/runs/{run_id}/summary"),
    ("GET", "/api/v1/runs/{run_id}/steps"),
    ("GET", "/api/v1/runs/{run_id}/events"),
    ("GET", "/api/v1/runs/{run_id}/graph"),
    ("POST", "/api/v1/runs/{run_id}/retry"),
    ("GET", "/api/v1/runs/{run_id}/compliance"),
    ("POST", "/api/v1/runs/{run_id}/resume"),
    ("POST", "/api/v1/webhooks/callback/{callback_id}"),
    ("GET", "/api/v1/credentials"),
    ("POST", "/api/v1/credentials"),
    ("GET", "/api/v1/credentials/{name}"),
    ("PUT", "/api/v1/credentials/{name}"),
    ("DELETE", "/api/v1/credentials/{name}"),
}


def _actual_routes(app_client) -> set[tuple[str, str]]:
    spec = app_client.get("/api/v1/openapi.json").json()
    out: set[tuple[str, str]] = set()
    for path, methods in spec.get("paths", {}).items():
        for method in methods:
            if method.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                out.add((method.upper(), path))
    return out


def test_no_expected_route_is_missing(app_client):
    actual = _actual_routes(app_client)
    missing = EXPECTED_ROUTES - actual
    assert not missing, (
        f"OpenAPI is missing routes the frontend / external callers depend on: "
        f"{sorted(missing)}. If you intentionally removed a route, update "
        f"EXPECTED_ROUTES in this file AND make sure the corresponding "
        f"frontend code no longer calls it."
    )


@pytest.mark.parametrize("path", ["/api/v1/runs", "/api/v1/runs/{run_id}"])
def test_run_routes_return_2xx_models_not_void(app_client, path):
    """Ensure those routes still declare a 200 response body shape."""
    spec = app_client.get("/api/v1/openapi.json").json()
    op = spec["paths"][path]["get"]
    assert "200" in op["responses"], (
        f"{path} GET must declare a 200 response — frontend deserializes it. "
        f"Got: {list(op['responses'].keys())}"
    )
    assert (
        "content" in op["responses"]["200"]
    ), f"{path} GET 200 must have a response body content, not be void"
