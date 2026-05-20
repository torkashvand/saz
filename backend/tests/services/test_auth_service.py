"""Service-level tests for the AuthService."""

import pytest
from sqlalchemy.orm import sessionmaker

from saz.api.errors import ConflictError, ValidationError
from saz.db.unit_of_work import UnitOfWork
from saz.security import verify_password
from saz.services.auth_service import AuthError, AuthService


def _service(db_engine):
    session = sessionmaker(bind=db_engine)()
    uow = UnitOfWork(session)
    uow.__enter__()
    return uow, session, AuthService(uow)


def test_register_user_persists_hashed_password(db_engine):
    uow, session, auth = _service(db_engine)
    try:
        user = auth.register_user(
            username="alice",
            email="alice@example.com",
            password="strong-password-1",
            display_name="Alice",
        )
        # password must not be stored in plaintext
        assert user.password_hash != "strong-password-1"
        assert verify_password("strong-password-1", user.password_hash)
        assert user.is_active is True
        assert user.username == "alice"
        assert user.email == "alice@example.com"
        assert user.display_name == "Alice"
    finally:
        session.close()


def test_register_user_rejects_duplicate_username(db_engine):
    uow, session, auth = _service(db_engine)
    try:
        auth.register_user(username="alice", email="a@example.com", password="strong-password-1")
        with pytest.raises(ConflictError):
            auth.register_user(
                username="alice", email="b@example.com", password="strong-password-2"
            )
    finally:
        session.close()


def test_register_user_rejects_duplicate_email(db_engine):
    uow, session, auth = _service(db_engine)
    try:
        auth.register_user(username="alice", email="a@example.com", password="strong-password-1")
        with pytest.raises(ConflictError):
            auth.register_user(username="bob", email="a@example.com", password="strong-password-2")
    finally:
        session.close()


def test_register_user_rejects_short_password(db_engine):
    uow, session, auth = _service(db_engine)
    try:
        with pytest.raises(ValidationError):
            auth.register_user(username="alice", email="a@example.com", password="short")
    finally:
        session.close()


def test_register_user_rejects_bad_email(db_engine):
    uow, session, auth = _service(db_engine)
    try:
        with pytest.raises(ValidationError):
            auth.register_user(username="alice", email="not-an-email", password="strong-password-1")
    finally:
        session.close()


def test_authenticate_accepts_username_or_email(db_engine):
    uow, session, auth = _service(db_engine)
    try:
        auth.register_user(
            username="alice", email="alice@example.com", password="strong-password-1"
        )
        # by username
        u1 = auth.authenticate("alice", "strong-password-1")
        assert u1.username == "alice"
        # by email
        u2 = auth.authenticate("alice@example.com", "strong-password-1")
        assert u2.id == u1.id
    finally:
        session.close()


def test_authenticate_rejects_wrong_password(db_engine):
    uow, session, auth = _service(db_engine)
    try:
        auth.register_user(
            username="alice", email="alice@example.com", password="strong-password-1"
        )
        with pytest.raises(AuthError):
            auth.authenticate("alice", "wrong-password")
    finally:
        session.close()


def test_authenticate_rejects_unknown_user(db_engine):
    uow, session, auth = _service(db_engine)
    try:
        with pytest.raises(AuthError):
            auth.authenticate("nobody", "anything")
    finally:
        session.close()


def test_authenticate_rejects_disabled_user(db_engine):
    uow, session, auth = _service(db_engine)
    try:
        user = auth.register_user(
            username="alice", email="alice@example.com", password="strong-password-1"
        )
        assert uow.users is not None
        uow.users.set_active(user.id, False)
        uow.commit()

        with pytest.raises(AuthError) as exc:
            auth.authenticate("alice", "strong-password-1")
        assert "disabled" in str(exc.value).lower()
    finally:
        session.close()


def test_authenticate_records_last_login(db_engine):
    uow, session, auth = _service(db_engine)
    try:
        user = auth.register_user(
            username="alice", email="alice@example.com", password="strong-password-1"
        )
        assert user.last_login_at is None
        auth.authenticate("alice", "strong-password-1")

        assert uow.users is not None
        refreshed = uow.users.get(user.id)
        assert refreshed is not None
        assert refreshed.last_login_at is not None
    finally:
        session.close()


def test_user_from_token_returns_active_user(db_engine):
    uow, session, auth = _service(db_engine)
    try:
        user = auth.register_user(
            username="alice", email="alice@example.com", password="strong-password-1"
        )
        token, _ = auth.issue_access_token(user)
        resolved = auth.user_from_token(token)
        assert resolved.id == user.id
    finally:
        session.close()


def test_user_from_token_rejects_disabled_user(db_engine):
    uow, session, auth = _service(db_engine)
    try:
        user = auth.register_user(
            username="alice", email="alice@example.com", password="strong-password-1"
        )
        token, _ = auth.issue_access_token(user)

        assert uow.users is not None
        uow.users.set_active(user.id, False)
        uow.commit()

        with pytest.raises(AuthError):
            auth.user_from_token(token)
    finally:
        session.close()


def test_user_from_token_rejects_deleted_user(db_engine):
    uow, session, auth = _service(db_engine)
    try:
        user = auth.register_user(
            username="alice", email="alice@example.com", password="strong-password-1"
        )
        token, _ = auth.issue_access_token(user)

        assert uow.users is not None
        deleted = uow.users.get(user.id)
        assert deleted is not None
        session.delete(deleted)
        session.commit()

        with pytest.raises(AuthError):
            auth.user_from_token(token)
    finally:
        session.close()
