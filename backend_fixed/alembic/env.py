"""
alembic/env.py

Alembic migration environment for the AI Order Supervisor Postgres
read-model mirror (see ARCHITECTURE.md §8, db/models.py).

Reads the database URL from the `DATABASE_URL` environment variable (falling
back to `sqlalchemy.url` in alembic.ini if set there instead), and uses
`db.base.Base.metadata` as the source of truth for autogenerate.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# --------------------------------------------------------------------------
# Model imports — required so that Base.metadata is fully populated before
# autogenerate compares it against the live database. Importing db.models
# registers Supervisor, Run, Event, and Action on Base.metadata via their
# declarative class bodies.
# --------------------------------------------------------------------------
from db.base import Base
import db.models  # noqa: F401  (side-effecting import, registers tables)

# Alembic Config object, provides access to values within alembic.ini.
config = context.config

# Interpret the config file for Python logging (writes to file if configured).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata object used for 'autogenerate' support.
target_metadata = Base.metadata


def _get_url() -> str:
    """
    Resolve the database URL. Prefer the DATABASE_URL environment variable
    (typical for containerized/CI environments); fall back to whatever is
    configured in alembic.ini under sqlalchemy.url.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    ini_url = config.get_main_option("sqlalchemy.url")
    if not ini_url:
        raise RuntimeError(
            "No database URL configured. Set the DATABASE_URL environment "
            "variable or set sqlalchemy.url in alembic.ini."
        )
    return ini_url


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine, though an
    Engine is acceptable here as well. By skipping the Engine creation we
    don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the script
    output.
    """
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in online mode with the project's async DB driver."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
