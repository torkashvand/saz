"""AdminService-level tests — safety rails and audit attribution."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from saz.api.errors import ConflictError
from saz.db.models import User
from saz.db.unit_of_work import UnitOfWork
from saz.security import hash_password, verify_password
from saz.services.admin_service import AdminError, AdminService


def _service(db_engine):
    session = sessionmaker(bind=db_engine)()
    uow = UnitOfWork(session)
    uow.__enter__()
    return uow, session, AdminService(uow)


def _admin_actor(db_engine, *, username: str = "root_admin") -> User:
    with Session(db_engine) as s:
        from datetime import UTC, datetime

        u = User(
            id=f"actor-{username}",
            username=username,
            email=f"{username}@example.com",
            password_hash=hash_password("strong-password-1"),
            is_active=True,
            is_admin=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        s.add(u)
        s.commit()
        s.refresh(u)
        s.expunge(u)
        return u


def test_create_user_hashes_password_and_returns_row(db_engine):
    actor = _admin_actor(db_engine)
    uow, session, svc = _service(db_engine)
    try:
        u = svc.create_user(
            actor=actor,
            username="alice",
            email="alice@example.com",
            password="strong-password-1",
        )
        assert u.password_hash != "strong-password-1"
        assert verify_password("strong-password-1", u.password_hash)
        assert u.is_admin is False
        assert u.is_active is True
        assert u.must_change_password is False
    finally:
        session.close()


def test_reset_password_forces_change(db_engine):
    actor = _admin_actor(db_engine)
    uow, session, svc = _service(db_engine)
    try:
        target = svc.create_user(
            actor=actor,
            username="forgetful",
            email="f@example.com",
            password="initial-pw-1",
        )
        before_hash = target.password_hash
        svc.reset_password(actor=actor, user_id=target.id, temporary_password="new-temp-pw")
        refreshed = svc.get_user(target.id)
        assert refreshed is not None
        assert refreshed.must_change_password is True
        assert refreshed.password_hash != before_hash
        assert verify_password("new-temp-pw", refreshed.password_hash)
    finally:
        session.close()


def test_cannot_disable_last_active_admin(db_engine):
    # Pre-seed exactly one admin.
    actor = _admin_actor(db_engine, username="only_admin")
    uow, session, svc = _service(db_engine)
    try:
        # An actor different from the target — even if it's the same DB
        # row in spirit, we want to test the last-admin guard, not the
        # self-disable guard.
        with pytest.raises(AdminError):
            # Use a fake "other" actor to bypass the self-disable rail.
            other_actor = User(
                id="some-other-actor",
                username="other",
                email="o@example.com",
                password_hash="x",
                is_admin=True,
                is_active=True,
            )
            svc.set_active(actor=other_actor, user_id=actor.id, is_active=False)
    finally:
        session.close()


def test_cannot_demote_last_active_admin(db_engine):
    actor = _admin_actor(db_engine, username="only_admin2")
    uow, session, svc = _service(db_engine)
    try:
        other_actor = User(
            id="some-other-actor-2",
            username="other2",
            email="o2@example.com",
            password_hash="x",
            is_admin=True,
            is_active=True,
        )
        with pytest.raises(AdminError):
            svc.set_admin(actor=other_actor, user_id=actor.id, is_admin=False)
    finally:
        session.close()


def test_cannot_self_disable(db_engine):
    actor = _admin_actor(db_engine, username="self_disabler")
    # Add a second admin so the last-admin guard isn't what trips us.
    with Session(db_engine) as s:
        from datetime import UTC, datetime

        s.add(
            User(
                id="another-admin",
                username="another_admin",
                email="another@example.com",
                password_hash=hash_password("x" * 12),
                is_active=True,
                is_admin=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        s.commit()

    uow, session, svc = _service(db_engine)
    try:
        with pytest.raises(AdminError, match="own account"):
            svc.set_active(actor=actor, user_id=actor.id, is_active=False)
    finally:
        session.close()


def test_update_profile_rejects_duplicate_email(db_engine):
    actor = _admin_actor(db_engine, username="updater_admin")
    uow, session, svc = _service(db_engine)
    try:
        svc.create_user(
            actor=actor,
            username="user_one",
            email="one@example.com",
            password="pw-1-strong",
        )
        u2 = svc.create_user(
            actor=actor,
            username="user_two",
            email="two@example.com",
            password="pw-2-strong",
        )
        with pytest.raises(ConflictError):
            svc.update_profile(actor=actor, user_id=u2.id, email="one@example.com")
    finally:
        session.close()
