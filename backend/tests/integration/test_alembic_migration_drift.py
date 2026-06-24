"""Alembic ``head`` must match what SQLAlchemy metadata declares.

If the ORM models drift from the migration history, fresh installs and
prod databases disagree. This test:
  1. Creates a fresh, empty PostgreSQL database.
  2. Runs alembic upgrade head against it.
  3. Inspects the resulting schema and compares to
     ``Base.metadata.tables`` — every table must exist, and every model
     column must have a matching column in the migrated schema.

It tolerates extra columns added in migrations but not yet on the model, but
treats *missing* tables/columns as a real drift to fix.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from alembic import command
from alembic.config import Config
from saz.db.models import Base


def _alembic_ini_path() -> Path:
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root / "alembic.ini"


def _table_names_lower(inspector) -> set[str]:
    return {t.lower() for t in inspector.get_table_names()}


def _admin_exec(admin_url, statements: list[str]) -> None:
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            for stmt in statements:
                conn.exec_driver_sql(stmt)
    finally:
        admin.dispose()


@pytest.fixture
def migrated_db(monkeypatch):
    ini_path = _alembic_ini_path()
    if not ini_path.exists():
        pytest.skip(f"no alembic.ini at {ini_path}")

    base = make_url(
        os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg2://saz:saz@localhost:5433/saz_test")
    )
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    mig_db = f"{base.database}_mig_{worker}"
    admin_url = base.set(database="postgres")
    mig_url = base.set(database=mig_db)
    url_str = mig_url.render_as_string(hide_password=False)

    drop = [
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{mig_db}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{mig_db}"',
    ]
    _admin_exec(admin_url, [*drop, f'CREATE DATABASE "{mig_db}"'])
    try:
        cfg = Config(str(ini_path))
        cfg.set_main_option("sqlalchemy.url", url_str)
        # env.py reads DATABASE_URL from the environment; override it so alembic
        # migrates the fresh database we inspect.
        monkeypatch.setenv("DATABASE_URL", url_str)
        monkeypatch.setenv(
            "PYTHONPATH",
            f"{ini_path.parent}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
        )
        command.upgrade(cfg, "head")
        engine = create_engine(url_str)
        yield engine
        engine.dispose()
    finally:
        _admin_exec(admin_url, drop)


def test_every_model_table_exists_after_migration(migrated_db):
    inspector = inspect(migrated_db)
    migrated_tables = _table_names_lower(inspector)
    expected_tables = {t.name.lower() for t in Base.metadata.tables.values()}
    missing = expected_tables - migrated_tables
    assert not missing, (
        f"Tables declared on SQLAlchemy models but missing in migrated schema: "
        f"{sorted(missing)}. Migration head is out of sync with ORM models — "
        f"add the missing CREATE TABLE / ADD COLUMN to alembic/versions/."
    )


def test_every_model_column_exists_after_migration(migrated_db):
    inspector = inspect(migrated_db)
    missing: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name.lower() not in _table_names_lower(inspector):
            continue  # surfaced by the table-level test
        migrated_cols = {c["name"].lower() for c in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name.lower() not in migrated_cols:
                missing.append(f"{table_name}.{column.name}")
    assert not missing, (
        f"Columns on SQLAlchemy models but absent from migrated schema: "
        f"{missing}. Add an ALTER TABLE migration."
    )
