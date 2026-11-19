"""Database engine, sessions and the readiness check (DESIGN §7.4).

Interview notes:
- One async engine per process, created in the app lifespan and disposed on shutdown.
- Neon suspends idle compute and drops connections, so the pool pings before reuse
  (pool_pre_ping) and recycles connections after a few minutes.
- check_database() never raises and never hangs: /readyz must answer quickly either way.
"""

import asyncio
import ssl
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as _create_async_engine

from app.core.config import Settings

log = structlog.get_logger(__name__)


# Something that opens a new DB session: `async with factory() as session: ...`.
# An async_sessionmaker is one; tests pass one that hands out their rolled-back session.
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def create_engine(settings: Settings) -> AsyncEngine:
    connect_args: dict[str, object] = {}
    if settings.database_ssl:
        # Verifies the server certificate and hostname (stricter than libpq's sslmode=require).
        connect_args["ssl"] = ssl.create_default_context()

    return _create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args=connect_args,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: objects stay usable after commit (needed in async code,
    # where lazy-refreshing an expired attribute would need an implicit await).
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_database(engine: AsyncEngine, timeout_seconds: float = 2.0) -> bool:
    """Return True if `SELECT 1` succeeds within the timeout, else False."""
    try:
        async with asyncio.timeout(timeout_seconds):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except (TimeoutError, OSError, SQLAlchemyError) as exc:
        log.warning("database_unreachable", error_type=type(exc).__name__)
        return False
    return True
