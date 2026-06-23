"""User.role column and the is_admin compatibility property.

`role` is the single source of truth for a user's authorization tier;
`is_admin` is kept as a derived hybrid property so existing call sites and
SQL filters keep working while the column is retired.
"""

from sqlalchemy.orm import sessionmaker

from saz.domain.literals import Role
from saz.repositories.write.user_repository import UserRepository


def _session(db_engine):
    return sessionmaker(bind=db_engine)()


def test_role_enum_has_three_tiers():
    assert set(Role) == {Role.ADMIN, Role.OPERATOR, Role.VIEWER}
    assert Role.ADMIN == "admin"
    assert Role.OPERATOR == "operator"
    assert Role.VIEWER == "viewer"


def test_new_user_defaults_to_operator(db_engine):
    session = _session(db_engine)
    try:
        repo = UserRepository(session)
        user = repo.create(username="op1", email="op1@example.com", password_hash="x")
        session.flush()
        assert user.role == Role.OPERATOR
        assert user.is_admin is False
    finally:
        session.close()


def test_create_with_role_admin_reports_is_admin(db_engine):
    session = _session(db_engine)
    try:
        repo = UserRepository(session)
        user = repo.create(
            username="ad1", email="ad1@example.com", password_hash="x", role=Role.ADMIN
        )
        session.flush()
        assert user.role == Role.ADMIN
        assert user.is_admin is True
    finally:
        session.close()


def test_setting_is_admin_false_demotes_to_operator(db_engine):
    session = _session(db_engine)
    try:
        repo = UserRepository(session)
        user = repo.create(
            username="ad2", email="ad2@example.com", password_hash="x", role=Role.ADMIN
        )
        session.flush()
        user.is_admin = False
        session.flush()
        assert user.role == Role.OPERATOR
        assert user.is_admin is False
    finally:
        session.close()


def test_viewer_role_is_not_admin(db_engine):
    session = _session(db_engine)
    try:
        repo = UserRepository(session)
        user = repo.create(username="vw1", email="vw1@example.com", password_hash="x")
        user.role = Role.VIEWER
        session.flush()
        assert user.is_admin is False
        assert user.role == Role.VIEWER
    finally:
        session.close()


def test_count_active_admins_filters_by_role(db_engine):
    session = _session(db_engine)
    try:
        repo = UserRepository(session)
        # Seeded "testuser" is an operator; add one admin and one viewer.
        repo.create(username="ad3", email="ad3@example.com", password_hash="x", role=Role.ADMIN)
        viewer = repo.create(username="vw2", email="vw2@example.com", password_hash="x")
        viewer.role = Role.VIEWER
        session.flush()
        assert repo.count_active_admins() == 1
    finally:
        session.close()
