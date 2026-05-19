"""CredentialService tests — encryption at rest, round-trip, no leakage."""

import pytest
import yaml
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from saz.db.models import Credential
from saz.db.unit_of_work import UnitOfWork
from saz.services.credential_service import CredentialService
from saz.settings import settings


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    """Provide a per-test Fernet key so service init succeeds."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "CREDENTIALS_ENCRYPTION_KEY", key)
    yield key


def test_round_trip_returns_original_data(db_engine):
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            service = CredentialService(uow)
            service.create(
                name="gh_token",
                credential_type="api_token",
                data={"token": "ghp_super_secret_123"},
                description="GitHub PAT",
            )

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            service = CredentialService(uow)
            got = service.get("gh_token")

    assert got is not None
    assert got["name"] == "gh_token"
    assert got["type"] == "api_token"
    assert got["data"] == {"token": "ghp_super_secret_123"}


def test_data_is_encrypted_at_rest(db_engine):
    """The secret must not be recoverable by scanning the raw DB column."""
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            CredentialService(uow).create(
                name="leak_test",
                credential_type="api_token",
                data={"token": "PLAINTEXT_SHOULD_NOT_APPEAR"},
            )

    with Session(db_engine) as session:
        row = session.get(Credential, "leak_test")
        assert row is not None
        assert b"PLAINTEXT_SHOULD_NOT_APPEAR" not in row.data_encrypted, (
            "Credential data column must be encrypted at rest; plaintext "
            "secret was found in data_encrypted bytes."
        )
        # And the stored bytes should decrypt back to the original YAML
        key = settings.CREDENTIALS_ENCRYPTION_KEY
        plaintext = Fernet(key.encode()).decrypt(row.data_encrypted)
        assert yaml.safe_load(plaintext) == {"token": "PLAINTEXT_SHOULD_NOT_APPEAR"}


def test_update_preserves_type_and_changes_data(db_engine):
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            CredentialService(uow).create(
                name="rotate_me",
                credential_type="ssh_key",
                data={"private_key": "v1"},
            )

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            CredentialService(uow).update("rotate_me", data={"private_key": "v2"})

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            got = CredentialService(uow).get("rotate_me")

    assert got["type"] == "ssh_key", "update() must not change credential type"
    assert got["data"] == {"private_key": "v2"}


def test_update_unknown_credential_raises(db_engine):
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            with pytest.raises(ValueError, match="not found"):
                CredentialService(uow).update("nope", data={"x": 1})


def test_list_returns_metadata_only(db_engine):
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            svc = CredentialService(uow)
            svc.create(name="meta_only", credential_type="api_token", data={"token": "SHHH"})

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            items = CredentialService(uow).list()

    assert len(items) == 1
    # The DTO is dataclass-like — verify the secret never made it onto the model
    blob = repr(items[0])
    assert "SHHH" not in blob, f"list DTO leaked secret value: {blob!r}"


def test_delete_returns_true_when_present_false_when_absent(db_engine):
    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            CredentialService(uow).create(
                name="delete_me", credential_type="api_token", data={"x": 1}
            )

    with Session(db_engine) as session:
        with UnitOfWork(session) as uow:
            svc = CredentialService(uow)
            assert svc.delete("delete_me") is True
            assert svc.delete("delete_me") is False, (
                "delete on a missing name must return False so callers can "
                "distinguish present-then-removed from absent."
            )
