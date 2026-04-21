"""Alembic environment configuration for async SQLAlchemy.

Loads the database URL from ``app.config.settings`` and uses the
``Base.metadata`` from ``app.core.database`` so that ``--autogenerate``
can detect model changes.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.core.database import Base

# Import all model modules so their tables are registered on Base.metadata.
# This is required for Alembic autogenerate to detect model changes.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401
import app.modules.customers.models  # noqa: F401
import app.modules.vehicles.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.invoices.models  # noqa: F401
import app.modules.payments.models  # noqa: F401
import app.modules.quotes.models  # noqa: F401
import app.modules.job_cards.models  # noqa: F401
import app.modules.bookings.models  # noqa: F401
import app.modules.notifications.models  # noqa: F401
import app.modules.webhooks.models  # noqa: F401
import app.modules.accounting.models  # noqa: F401
import app.modules.discounts.models  # noqa: F401

# Alembic Config object — gives access to alembic.ini values.
config = context.config

# Set the SQLAlchemy URL from application settings so it doesn't need
# to be duplicated in alembic.ini.
config.set_main_option("sqlalchemy.url", settings.database_url)

# Configure Python logging from the ini file.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# MetaData object for 'autogenerate' support.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_num_width=128,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations using the provided synchronous connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_num_width=128,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations in an async context."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
