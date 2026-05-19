"""Alembic ``head`` must match what SQLAlchemy metadata declares.

If the ORM models drift from the migration history, fresh installs and
prod databases disagree. This test:
  1. Spins up a temp SQLite database.
  2. Runs alembic upgrade head against it.
  3. Inspects the resulting schema and compares to
     ``Base.metadata.tables`` — every table must exist, and every model
     column must have a matching column in the migrated schema.

It tolerates some divergence (extra columns added in migrations but not
yet on the model, type aliases SQLite collapses) but treats *missing*
tables/columns as a real drift to fix.
"""

import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from alembic import command
from alembic.config import Config
from saz.db.models import Base


def _alembic_ini_path() -> Path:
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root / "alembic.ini"


def _table_names_lower(inspector) -> set[str]:
    return {t.lower() for t in inspector.get_table_names()}


@pytest.fixture
def migrated_db(monkeypatch):
    ini_path = _alembic_ini_path()
    if not ini_path.exists():
        pytest.skip(f"no alembic.ini at {ini_path}")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    url = f"sqlite:///{db_path}"
    try:
        cfg = Config(str(ini_path))
        cfg.set_main_option("sqlalchemy.url", url)
        # env.py reads DATABASE_URL from the environment; conftest pins it to
        # :memory: globally, so we must override it for the duration of the
        # upgrade or alembic migrates a different database than we inspect.
        backend_root = ini_path.parent
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv(
            "PYTHONPATH",
            f"{backend_root}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
        )
        command.upgrade(cfg, "head")
        engine = create_engine(url)
        yield engine
        engine.dispose()
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


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
