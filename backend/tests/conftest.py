"""Shared test fixtures.

Tests never read the developer's real environment or `.env`: `clean_env` removes every
config variable first, and `load_config(env_file=None)` skips the `.env` file.
"""

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_extractor, get_session
from app.core.config import Settings, load_config
from app.core.db import create_engine
from app.core.rate_limit import AuthLimiters, SlidingWindowLimiter
from app.factory import create_app
from app.services.extraction.extractors import Extractor
from tests.helpers import INVITE_CODE, with_database_url

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

VALID_ENV: dict[str, str] = {
    "ENVIRONMENT": "test",
    # Port 1: nothing ever listens there, so unit tests behave the same whether or not a
    # Postgres is running (locally or in CI). Real-DB tests use TEST_DATABASE_URL explicitly.
    "DATABASE_URL": "postgresql://driveradar:driveradar@127.0.0.1:1/driveradar",
    "ALLOWED_ORIGINS": "http://localhost:5173",
    "BATCH_INVITE_CODE": INVITE_CODE,
    "CRON_SECRET": "cron-secret-0123456789",
}


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio (the event loop FastAPI uses)."""
    return "asyncio"


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Remove every config variable so each test controls the environment exactly."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    yield monkeypatch


@pytest.fixture
def valid_env(clean_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """A minimal valid environment: only the required variables are set."""
    for key, value in VALID_ENV.items():
        clean_env.setenv(key, value)
    return clean_env


@pytest.fixture
def settings(valid_env: pytest.MonkeyPatch) -> Settings:
    return load_config(env_file=None)


# ---------------------------------------------------------------- real Postgres
#
# Integration tests run against TEST_DATABASE_URL (CI's Postgres 17 service, or the local
# Docker one) and are skipped when it isn't set. Isolation: each test runs inside one
# transaction that is rolled back at the end, so tests never see each other's rows and the
# seed data from the migrations stays untouched.


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Migrate the test database to head once per test run, then return its URL."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("needs a real Postgres (set TEST_DATABASE_URL)")
    with pytest.MonkeyPatch.context() as mp:
        # alembic/env.py reads its config from env vars, like the app does.
        for key, value in {**VALID_ENV, "DATABASE_URL": url}.items():
            mp.setenv(key, value)
        command.upgrade(Config(str(ALEMBIC_INI)), "head")
    return url


@pytest.fixture
async def db_session(test_database_url: str, settings: Settings) -> AsyncIterator[AsyncSession]:
    """A session inside a transaction that is always rolled back.

    join_transaction_mode="create_savepoint": if code under test calls commit() or
    rollback(), it only affects a SAVEPOINT, never the outer transaction we roll back.
    """
    engine = create_engine(with_database_url(settings, test_database_url))
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(
                bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            try:
                yield session
            finally:
                await session.close()
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def api(settings: Settings, db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client for the app whose requests all use `db_session`.

    httpx's ASGITransport runs the app in the test's own event loop (TestClient uses a
    separate thread and loop, and an asyncpg connection can't be shared across loops).
    The lifespan isn't run, so no app engine is created: every DB call goes through the
    overridden get_session. https, because the cookie jar (like a browser) never sends a
    Secure cookie over plain http.
    """
    async with api_client(settings, db_session) as client:
        yield client


@asynccontextmanager
async def api_client(
    settings: Settings,
    db_session: AsyncSession,
    limiters: AuthLimiters | None = None,
    *,
    extractor: Extractor | None = None,
    extraction_limiter: SlidingWindowLimiter | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    """Like the `api` fixture, for tests that need different settings, limits or a fake
    extractor (CI never calls a real LLM).

    Sends the frontend's Origin on every request, like a browser on our site would.
    """
    app = create_app(settings)
    app.dependency_overrides[get_session] = lambda: db_session
    if limiters is not None:
        app.state.auth_limiters = limiters
    if extractor is not None:
        app.dependency_overrides[get_extractor] = lambda: extractor
    if extraction_limiter is not None:
        app.state.extraction_limiter = extraction_limiter
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://test",
        headers={"Origin": settings.allowed_origins[0]},
    ) as client:
        yield client
