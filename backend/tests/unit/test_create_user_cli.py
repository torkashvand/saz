"""Smoke test for the saz.scripts.create_user CLI.

The CLI is the only way to mint the first admin without already having
admin credentials. These tests pin the contract: it creates an admin
by default, refuses duplicate usernames cleanly, never logs the
plaintext password, and routes through AuthService so password hashing
happens.
"""

from unittest.mock import patch

from sqlalchemy.orm import Session

from saz.db.models import User
from saz.scripts.create_user import main as create_user_main


def _run_with_session(db_engine, argv: list[str]) -> int:
    """Patch SessionLocal so the CLI writes into the test database."""
    from sqlalchemy.orm import sessionmaker

    SessionFactory = sessionmaker(bind=db_engine)
    with patch("saz.scripts.create_user.SessionLocal", SessionFactory):
        return create_user_main(argv)


def test_cli_creates_admin_by_default(db_engine, capsys):
    rc = _run_with_session(
        db_engine,
        ["--username", "rootadmin", "--email", "root@example.com", "--password", "very-strong-pw"],
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "created admin rootadmin" in out
    # Plaintext password must never appear in the CLI output.
    assert "very-strong-pw" not in out

    with Session(db_engine) as s:
        u = s.query(User).filter_by(username="rootadmin").one()
        assert u.is_admin is True
        assert u.is_active is True
        assert u.must_change_password is False
        # Hash is stored, not plaintext.
        assert u.password_hash != "very-strong-pw"


def test_cli_no_admin_flag_creates_normal_user(db_engine, capsys):
    rc = _run_with_session(
        db_engine,
        [
            "--username",
            "normie",
            "--email",
            "normie@example.com",
            "--password",
            "very-strong-pw",
            "--no-admin",
        ],
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "created user normie" in out

    with Session(db_engine) as s:
        u = s.query(User).filter_by(username="normie").one()
        assert u.is_admin is False


def test_cli_rejects_duplicate_username(db_engine, capsys):
    _run_with_session(
        db_engine,
        ["--username", "dupe", "--email", "a@example.com", "--password", "very-strong-pw"],
    )
    # Second attempt with same username must fail.
    try:
        _run_with_session(
            db_engine,
            ["--username", "dupe", "--email", "b@example.com", "--password", "very-strong-pw"],
        )
        raised = False
    except Exception:
        raised = True
    assert raised, "CLI should raise on duplicate username"


def test_cli_rejects_short_password(db_engine):
    try:
        _run_with_session(
            db_engine,
            ["--username", "shorty", "--email", "s@example.com", "--password", "short"],
        )
        raised = False
    except Exception:
        raised = True
    assert raised, "CLI should reject too-short passwords"
