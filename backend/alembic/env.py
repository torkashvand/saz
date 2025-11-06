"""Alembic environment configuration."""

import logging
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context

# Import models
from saz.db.models import Base

# This is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

# Override sqlalchemy.url from environment variable
db_url = os.getenv("DATABASE_URL")
if not db_url:
    raise ValueError("DATABASE_URL environment variable is not set")

config.set_main_option("sqlalchemy.url", db_url)
logger.info(f"Using database: {db_url.split('@')[1] if '@' in db_url else db_url}")

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """

    def process_revision_directives(context, revision, directives):  # type: ignore[no-untyped-def]
        """Prevent auto-migration when there are no changes to the schema."""
        if getattr(config.cmd_opts, "autogenerate", False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info("No changes in schema detected.")

    config_section = config.get_section(config.config_ini_section)
    if config_section is None:
        raise ValueError("Config section not found!")

    engine = engine_from_config(
        config_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    connection = engine.connect()
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        process_revision_directives=process_revision_directives,
        compare_type=True,
    )

    try:
        with context.begin_transaction():
            # Use PostgreSQL advisory lock to prevent concurrent migrations
            connection.execute(text("SELECT pg_advisory_xact_lock(1000);"))
            context.run_migrations()
    finally:
        connection.execute(text("SELECT pg_advisory_unlock(1000);"))
        connection.close()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
