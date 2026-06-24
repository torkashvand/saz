"""OIDC Authorization Code + PKCE login.

The HTTP/crypto seams (discovery, code exchange, ID-token verification) are
faked so the tests exercise PKCE URL construction, state validation, and the
identity-resolution policy (existing link / link-by-verified-email / JIT /
refuse) without a live IdP.
"""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

import saz.services.oidc_service as oidc_mod
from saz.db.unit_of_work import UnitOfWork
from saz.domain.literals import Role
from saz.security.secret_box import encrypt_secret
from saz.services.oidc_service import OidcError, OidcService

ISSUER = "https://idp.example.com"
DISCOVERY = {
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/jwks",
    "issuer": ISSUER,
}


def _uow(db_engine):
    session = sessionmaker(bind=db_engine)()
    uow = UnitOfWork(session)
    uow.__enter__()
    return uow, session


def _seed_provider(uow, **overrides):
    kwargs = dict(
        provider_key="okta",
        display_name="Okta",
        issuer=ISSUER,
        client_id="client-id",
        client_secret_encrypted=encrypt_secret("the-secret"),
        enabled=True,
    )
    kwargs.update(overrides)
    provider = uow.auth_providers.create(**kwargs)
    uow.commit()
    return provider


def _patch_seams(monkeypatch, claims):
    monkeypatch.setattr(oidc_mod, "fetch_discovery_document", lambda issuer: DISCOVERY)
    monkeypatch.setattr(oidc_mod, "exchange_code", lambda *a, **k: {"id_token": "fake.jwt"})
    monkeypatch.setattr(oidc_mod, "verify_id_token", lambda id_token, **k: claims)


def _begin(svc):
    url, tx = svc.begin("okta")
    state = parse_qs(urlparse(url).query)["state"][0]
    return url, tx, state


def test_begin_builds_pkce_authorization_url(db_engine, monkeypatch):
    monkeypatch.setattr(oidc_mod, "fetch_discovery_document", lambda issuer: DISCOVERY)
    uow, session = _uow(db_engine)
    try:
        _seed_provider(uow)
        url, tx, state = _begin(OidcService(uow))
        q = parse_qs(urlparse(url).query)
        assert url.startswith(f"{ISSUER}/authorize")
        assert q["response_type"] == ["code"]
        assert q["code_challenge_method"] == ["S256"]
        assert q["code_challenge"] and q["nonce"] and state
        assert q["redirect_uri"][0].endswith("/api/v1/auth/oidc/okta/callback")
        # No offline_access in the default scopes -> no forced consent prompt.
        assert "prompt" not in q
    finally:
        session.close()


def test_begin_forces_consent_prompt_for_offline_access(db_engine, monkeypatch):
    """IdPs (e.g. GEANT/SATOSA) reject offline_access without prompt=consent."""
    monkeypatch.setattr(oidc_mod, "fetch_discovery_document", lambda issuer: DISCOVERY)
    uow, session = _uow(db_engine)
    try:
        _seed_provider(uow, scopes="openid profile email offline_access")
        url, _tx, _state = _begin(OidcService(uow))
        q = parse_qs(urlparse(url).query)
        assert q["prompt"] == ["consent"]
    finally:
        session.close()


def test_complete_links_existing_user_by_verified_email(db_engine, monkeypatch):
    uow, session = _uow(db_engine)
    try:
        _seed_provider(uow)
        existing = uow.users.create(
            username="alice", email="alice@example.com", password_hash="x", role=Role.OPERATOR
        )
        uow.commit()
        _patch_seams(
            monkeypatch,
            {
                "iss": ISSUER,
                "sub": "subject-1",
                "email": "alice@example.com",
                "email_verified": True,
            },
        )
        svc = OidcService(uow)
        _url, tx, state = _begin(svc)
        token, _exp, secret = svc.complete("okta", code="c", state=state, tx_token=tx)
        assert token and secret
        identity = uow.external_identities.get_by_subject(ISSUER, "subject-1")
        assert identity is not None and identity.user_id == existing.id
    finally:
        session.close()


def test_complete_jit_creates_viewer(db_engine, monkeypatch):
    uow, session = _uow(db_engine)
    try:
        _seed_provider(uow, jit_enabled=True, default_role="viewer")
        _patch_seams(
            monkeypatch,
            {
                "iss": ISSUER,
                "sub": "subject-2",
                "email": "newby@example.com",
                "email_verified": True,
            },
        )
        svc = OidcService(uow)
        _url, tx, state = _begin(svc)
        svc.complete("okta", code="c", state=state, tx_token=tx)
        created = uow.users.get_by_email("newby@example.com")
        assert created is not None
        assert created.role == Role.VIEWER
    finally:
        session.close()


def test_complete_public_client_omits_client_secret(db_engine, monkeypatch):
    """A provider with no stored secret (public/PKCE client) must exchange the
    code with client_secret=None and still sign the user in."""
    uow, session = _uow(db_engine)
    try:
        _seed_provider(
            uow,
            provider_key="okta",
            client_secret_encrypted=None,
            jit_enabled=True,
            default_role="viewer",
        )
        captured = {}

        def fake_exchange(token_endpoint, **kwargs):
            captured.update(kwargs)
            return {"id_token": "fake.jwt"}

        monkeypatch.setattr(oidc_mod, "fetch_discovery_document", lambda issuer: DISCOVERY)
        monkeypatch.setattr(oidc_mod, "exchange_code", fake_exchange)
        monkeypatch.setattr(
            oidc_mod,
            "verify_id_token",
            lambda id_token, **k: {
                "iss": ISSUER,
                "sub": "pub-1",
                "email": "pub@example.com",
                "email_verified": True,
            },
        )
        svc = OidcService(uow)
        _url, tx, state = _begin(svc)
        token, _exp, secret = svc.complete("okta", code="c", state=state, tx_token=tx)
        assert token and secret
        assert captured["client_secret"] is None
        assert captured["code_verifier"]
    finally:
        session.close()


def test_complete_refuses_when_no_link_and_jit_disabled(db_engine, monkeypatch):
    uow, session = _uow(db_engine)
    try:
        _seed_provider(uow, jit_enabled=False)
        _patch_seams(
            monkeypatch,
            {
                "iss": ISSUER,
                "sub": "subject-3",
                "email": "stranger@example.com",
                "email_verified": True,
            },
        )
        svc = OidcService(uow)
        _url, tx, state = _begin(svc)
        with pytest.raises(OidcError):
            svc.complete("okta", code="c", state=state, tx_token=tx)
    finally:
        session.close()


def test_complete_rejects_bad_state(db_engine, monkeypatch):
    uow, session = _uow(db_engine)
    try:
        _seed_provider(uow)
        _patch_seams(monkeypatch, {"iss": ISSUER, "sub": "s", "email_verified": True})
        svc = OidcService(uow)
        _url, tx, _state = _begin(svc)
        with pytest.raises(OidcError):
            svc.complete("okta", code="c", state="not-the-state", tx_token=tx)
    finally:
        session.close()


def test_complete_enforces_domain_allowlist(db_engine, monkeypatch):
    uow, session = _uow(db_engine)
    try:
        _seed_provider(uow, jit_enabled=True, allowed_domains="corp.example")
        _patch_seams(
            monkeypatch,
            {"iss": ISSUER, "sub": "subject-4", "email": "x@other.com", "email_verified": True},
        )
        svc = OidcService(uow)
        _url, tx, state = _begin(svc)
        with pytest.raises(OidcError):
            svc.complete("okta", code="c", state=state, tx_token=tx)
    finally:
        session.close()


def test_begin_wraps_discovery_failure_as_oidc_error(db_engine, monkeypatch):
    # An unreachable/misconfigured issuer must surface as OidcError (which the
    # route turns into a friendly ?sso=error redirect), never a raw httpx error
    # that would 500.
    def boom(issuer: str):
        raise httpx.ConnectError("nodename nor servname provided")

    monkeypatch.setattr(oidc_mod, "fetch_discovery_document", boom)
    uow, session = _uow(db_engine)
    try:
        _seed_provider(uow)
        with pytest.raises(OidcError):
            OidcService(uow).begin("okta")
    finally:
        session.close()


def test_start_route_redirects_to_login_on_discovery_failure(
    unauthenticated_app_client, db_engine, monkeypatch
):
    def boom(issuer: str):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(oidc_mod, "fetch_discovery_document", boom)
    uow, session = _uow(db_engine)
    try:
        _seed_provider(uow)
    finally:
        session.close()

    resp = unauthenticated_app_client.get("/api/v1/auth/oidc/okta/start", follow_redirects=False)
    assert resp.status_code == 303
    assert "sso=error" in resp.headers["location"]


# --- Route-level smoke: start redirect + cookie, callback happy path ---


def test_oidc_start_redirects_with_tx_cookie(unauthenticated_app_client, db_engine, monkeypatch):
    monkeypatch.setattr(oidc_mod, "fetch_discovery_document", lambda issuer: DISCOVERY)
    uow, session = _uow(db_engine)
    try:
        _seed_provider(uow)
    finally:
        session.close()

    resp = unauthenticated_app_client.get("/api/v1/auth/oidc/okta/start", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith(f"{ISSUER}/authorize")
    assert "saz_oidc_tx" in resp.cookies


def test_oidc_callback_signs_in_and_sets_refresh_cookie(
    unauthenticated_app_client, db_engine, monkeypatch
):
    uow, session = _uow(db_engine)
    try:
        _seed_provider(uow, jit_enabled=True, default_role="viewer")
    finally:
        session.close()
    _patch_seams(
        monkeypatch,
        {"iss": ISSUER, "sub": "subject-9", "email": "sso@example.com", "email_verified": True},
    )

    client = unauthenticated_app_client
    start = client.get("/api/v1/auth/oidc/okta/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

    cb = client.get(
        f"/api/v1/auth/oidc/okta/callback?code=abc&state={state}", follow_redirects=False
    )
    assert cb.status_code == 303
    assert "sso=ok" in cb.headers["location"]
    from saz.settings import settings

    assert settings.REFRESH_COOKIE_NAME in cb.cookies
