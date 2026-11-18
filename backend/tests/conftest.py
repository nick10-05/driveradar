"""Shared test fixtures.

Tests never read the developer's real environment or `.env`: `clean_env` removes every
config variable first, and `load_config(env_file=None)` skips the `.env` file.
"""

from collections.abc import Iterator

import pytest

from app.core.config import Settings, load_config

VALID_ENV: dict[str, str] = {
    "ENVIRONMENT": "test",
    # Port 1: nothing ever listens there, so unit tests behave the same whether or not a
    # Postgres is running (locally or in CI). Real-DB tests use TEST_DATABASE_URL explicitly.
    "DATABASE_URL": "postgresql://driveradar:driveradar@127.0.0.1:1/driveradar",
    "ALLOWED_ORIGINS": "http://localhost:5173",
    "BATCH_INVITE_CODE": "invite-code-123",
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
