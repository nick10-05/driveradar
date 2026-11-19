"""check_database(): a short `SELECT 1` used by /readyz. Must never hang or raise."""

import os
import time

import pytest

from app.core.config import Settings
from app.core.db import check_database, create_engine
from tests.helpers import with_database_url

pytestmark = pytest.mark.anyio


async def test_unreachable_database_returns_false(settings: Settings) -> None:
    # Port 1 on localhost: nothing listens there, so the connection is refused at once.
    engine = create_engine(with_database_url(settings, "postgresql://u:p@127.0.0.1:1/db"))
    try:
        assert await check_database(engine, timeout_seconds=2.0) is False
    finally:
        await engine.dispose()


async def test_hanging_database_times_out_instead_of_blocking(settings: Settings) -> None:
    # 10.255.255.1 is non-routable: packets are dropped, so a connect attempt would hang.
    engine = create_engine(with_database_url(settings, "postgresql://u:p@10.255.255.1:5432/db"))
    try:
        started = time.monotonic()
        assert await check_database(engine, timeout_seconds=0.5) is False
        assert time.monotonic() - started < 3
    finally:
        await engine.dispose()


@pytest.mark.db
@pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="needs a real Postgres")
async def test_reachable_database_returns_true(settings: Settings) -> None:
    engine = create_engine(with_database_url(settings, os.environ["TEST_DATABASE_URL"]))
    try:
        assert await check_database(engine) is True
    finally:
        await engine.dispose()
