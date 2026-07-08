"""Credentials API endpoint tests.

Most-important invariants for these routes:
  - Secret values never appear in any response (list, detail, after
    create/update).
  - Encryption-at-rest is round-trippable through CRUD.
  - 404 on get/update for unknown names.
"""

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from saz.db.models import Credential
from saz.settings import settings


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "CREDENTIALS_ENCRYPTION_KEY", key)
    yield key


SECRET_VALUE = "ghp_DO_NOT_LEAK_THIS_TOKEN_999"


def test_create_returns_metadata_without_secret(app_client):
    resp = app_client.post(
        "/api/v1/credentials",
        json={
            "name": "api_cred_1",
            "type": "api_token",
            "description": "test",
            "data": {"token": SECRET_VALUE},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "data" not in body, f"create response leaked data field: {body!r}"
    assert SECRET_VALUE not in resp.text, "secret value leaked in create response"
    assert body["name"] == "api_cred_1"
    assert body["type"] == "api_token"


def test_list_does_not_leak_secret(app_client):
    app_client.post(
        "/api/v1/credentials",
        json={"name": "api_cred_list", "type": "api_token", "data": {"token": SECRET_VALUE}},
    )

    resp = app_client.get("/api/v1/credentials")
    assert resp.status_code == 200, resp.text
    assert SECRET_VALUE not in resp.text, "GET /credentials returned secret value in response body"
    items = resp.json()["items"]
    assert any(i["name"] == "api_cred_list" for i in items)


def test_get_returns_metadata_only(app_client):
    app_client.post(
        "/api/v1/credentials",
        json={"name": "api_cred_get", "type": "api_token", "data": {"token": SECRET_VALUE}},
    )

    resp = app_client.get("/api/v1/credentials/api_cred_get")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "data" not in body
    assert SECRET_VALUE not in resp.text


def test_get_unknown_credential_returns_404(app_client):
    resp = app_client.get("/api/v1/credentials/does_not_exist")
    assert resp.status_code == 404, resp.text


def test_update_changes_data_without_leaking_either_value(app_client, db_engine):
    app_client.post(
        "/api/v1/credentials",
        json={"name": "api_cred_upd", "type": "api_token", "data": {"token": "v1_old"}},
    )

    resp = app_client.put(
        "/api/v1/credentials/api_cred_upd",
        json={"data": {"token": "v2_new"}},
    )
    assert resp.status_code == 200, resp.text
    assert (
        "v1_old" not in resp.text and "v2_new" not in resp.text
    ), "update response must not echo any secret value"

    # The encrypted blob at rest should not contain either plaintext
    with Session(db_engine) as session:
        row = session.get(Credential, "api_cred_upd")
        assert b"v1_old" not in row.data_encrypted
        assert b"v2_new" not in row.data_encrypted


def test_update_without_data_keeps_stored_secret(app_client, db_engine):
    """A metadata-only update (no `data` in the PUT body) must NOT wipe the
    stored secret — it used to be replaced with an empty payload."""
    app_client.post(
        "/api/v1/credentials",
        json={"name": "api_cred_meta", "type": "api_token", "data": {"token": "keep_me"}},
    )
    with Session(db_engine) as session:
        before = session.get(Credential, "api_cred_meta").data_encrypted

    resp = app_client.put(
        "/api/v1/credentials/api_cred_meta",
        json={"description": "updated description only"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "updated description only"

    with Session(db_engine) as session:
        after = session.get(Credential, "api_cred_meta").data_encrypted
    assert after == before, "metadata-only update replaced the stored secret payload"


def test_delete_removes_credential(app_client):
    app_client.post(
        "/api/v1/credentials",
        json={"name": "api_cred_del", "type": "api_token", "data": {"token": "x"}},
    )

    resp = app_client.delete("/api/v1/credentials/api_cred_del")
    assert resp.status_code == 200, resp.text

    resp = app_client.get("/api/v1/credentials/api_cred_del")
    assert resp.status_code == 404, "after delete, get must return 404"
