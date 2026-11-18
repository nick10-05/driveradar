"""Alembic migration environment.

Uses the app's own load_config() + create_engine(), so migrations get exactly the same
URL normalisation and SSL settings as the running app (one source of truth).
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from app.core.config import load_config
from app.core.db import create_engine
from app.core.logging import configure_logging
from app.models import Base

config = context.config
settings = load_config()

if context.is_offline_mode():
    # `--sql` prints SQL to stdout, so keep alembic.ini's plain stderr logging out of its way.
    if config.config_file_name is not None:
        fileConfig(config.config_file_name)
else:
    # Same structured (JSON in prod) logs as the app, e.g. migrations at container start.
    configure_logging(settings)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (`alembic upgrade head --sql`)."""
    context.configure(
        url=settings.database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_engine(settings)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
