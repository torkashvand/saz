"""Admin OIDC provider CRUD + the public provider list.

Security contract: client secrets are write-only (never returned), JIT can
never default to admin, and provider management is admin-only.
"""

import pytest
from sqlalchemy.orm import Session

from saz.db.models import User
from saz.domain.literals import Role
from tests.conftest import TEST_USER_ID


@pytest.fixture
def admin_user(db_engine):
    with Session(db_engine) as s:
        u = s.get(User, TEST_USER_ID)
        assert u is not None
        u.role = Role.ADMIN
        s.commit()
    yield


def _create_body(**overrides):
    body = {
        "provider_key": "okta",
        "display_name": "Okta",
        "issuer": "https://example.okta.com",
        "client_id": "client-123",
        "client_secret": "super-secret-value",
    }
    body.update(overrides)
    return body


def test_non_admin_cannot_list_providers(app_client):
    assert app_client.get("/api/v1/admin/auth/providers").status_code == 403


def test_non_admin_cannot_create_provider(app_client):
    resp = app_client.post("/api/v1/admin/auth/providers", json=_create_body())
    assert resp.status_code == 403


def test_admin_creates_provider_without_leaking_secret(app_client, admin_user):
    resp = app_client.post("/api/v1/admin/auth/providers", json=_create_body())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["provider_key"] == "okta"
    assert body["issuer"] == "https://example.okta.com"
    assert body["default_role"] == "viewer"
    assert body["enabled"] is False
    # The secret must never appear in the response, anywhere.
    assert "client_secret" not in body
    assert "super-secret-value" not in resp.text


def test_admin_creates_public_client_without_secret(app_client, admin_user, db_engine):
    """Public (PKCE-only) clients have no secret; create must succeed and
    persist no stored secret."""
    body = _create_body(provider_key="spa", client_secret=None)
    resp = app_client.post("/api/v1/admin/auth/providers", json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["provider_key"] == "spa"

    from saz.db.models import AuthProvider

    with Session(db_engine) as s:
        provider = s.query(AuthProvider).filter_by(provider_key="spa").one()
        assert provider.client_secret_encrypted is None


def test_admin_creates_provider_with_redirect_uri_override(app_client, admin_user):
    custom = "http://localhost:3000/api/auth/callback/oidc"
    body = _create_body(provider_key="rd", redirect_uri=custom)
    resp = app_client.post("/api/v1/admin/auth/providers", json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["redirect_uri"] == custom


def test_admin_creates_provider_with_trust_email_verified(app_client, admin_user):
    body = _create_body(provider_key="tev", trust_email_verified=True)
    resp = app_client.post("/api/v1/admin/auth/providers", json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["trust_email_verified"] is True


def test_create_duplicate_provider_key_conflicts(app_client, admin_user):
    assert app_client.post("/api/v1/admin/auth/providers", json=_create_body()).status_code == 201
    dup = app_client.post("/api/v1/admin/auth/providers", json=_create_body())
    assert dup.status_code == 409


def test_jit_default_role_cannot_be_admin(app_client, admin_user):
    resp = app_client.post("/api/v1/admin/auth/providers", json=_create_body(default_role="admin"))
    assert resp.status_code == 422


def test_admin_updates_and_enables_provider(app_client, admin_user):
    created = app_client.post("/api/v1/admin/auth/providers", json=_create_body()).json()
    pid = created["id"]
    resp = app_client.patch(
        f"/api/v1/admin/auth/providers/{pid}",
        json={"enabled": True, "display_name": "Okta Prod", "client_secret": "rotated"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is True
    assert body["display_name"] == "Okta Prod"
    assert "rotated" not in resp.text


def test_admin_deletes_provider(app_client, admin_user):
    pid = app_client.post("/api/v1/admin/auth/providers", json=_create_body()).json()["id"]
    assert app_client.delete(f"/api/v1/admin/auth/providers/{pid}").status_code == 204
    assert app_client.get("/api/v1/admin/auth/providers").json()["total"] == 0


def test_public_providers_lists_only_enabled(app_client, admin_user):
    # Disabled provider is hidden; enabled one is exposed with a start URL.
    app_client.post("/api/v1/admin/auth/providers", json=_create_body(provider_key="disabled"))
    enabled = app_client.post(
        "/api/v1/admin/auth/providers",
        json=_create_body(provider_key="google", display_name="Google", enabled=True),
    )
    assert enabled.status_code == 201

    resp = app_client.get("/api/v1/auth/providers")
    assert resp.status_code == 200
    items = resp.json()
    keys = {p["provider_key"] for p in items}
    assert keys == {"google"}
    assert items[0]["start_url"] == "/api/v1/auth/oidc/google/start"
    assert "client_secret" not in resp.text


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://idp.example.com", "https://idp.example.com"),
        ("https://idp.example.com/", "https://idp.example.com"),
        (
            "https://idp.example.com/.well-known/openid-configuration",
            "https://idp.example.com",
        ),
        (
            "https://idp.example.com/.well-known/openid-configuration/",
            "https://idp.example.com",
        ),
        (" https://idp.example.com ", "https://idp.example.com"),
    ],
)
def test_normalize_issuer_strips_discovery_suffix(raw, expected):
    from saz.services.auth_provider_service import normalize_issuer

    assert normalize_issuer(raw) == expected


def test_fetch_discovery_does_not_double_well_known(monkeypatch):
    """Pasting the full discovery URL as the issuer must not produce a doubled
    /.well-known/openid-configuration path."""
    import saz.services.auth_provider_service as svc_mod

    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"issuer": "https://idp.example.com"}

    def fake_get(url, **kwargs):
        captured["url"] = url
        return _Resp()

    monkeypatch.setattr(svc_mod.httpx, "get", fake_get)
    svc_mod.fetch_discovery_document("https://idp.example.com/.well-known/openid-configuration")
    assert captured["url"] == "https://idp.example.com/.well-known/openid-configuration"


def test_create_normalizes_pasted_discovery_url_as_issuer(app_client, admin_user):
    body = _create_body(
        provider_key="geant",
        issuer="https://proxy.aai.geant.org/.well-known/openid-configuration",
    )
    resp = app_client.post("/api/v1/admin/auth/providers", json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["issuer"] == "https://proxy.aai.geant.org"


def test_provider_test_endpoint_reports_discovery(app_client, admin_user, monkeypatch):
    pid = app_client.post("/api/v1/admin/auth/providers", json=_create_body()).json()["id"]

    import saz.services.auth_provider_service as svc_mod

    def fake_discovery(issuer: str) -> dict:
        return {
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
        }

    monkeypatch.setattr(svc_mod, "fetch_discovery_document", fake_discovery)
    resp = app_client.post(f"/api/v1/admin/auth/providers/{pid}/test")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["authorization_endpoint"].endswith("/authorize")
