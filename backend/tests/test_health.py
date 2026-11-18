"""/healthz = the process is up. /readyz = the process can reach the database."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.health import database_ready
from app.core.config import Settings
from app.factory import create_app


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:  # `with` runs the lifespan (startup + shutdown)
        yield test_client


def test_healthz_is_ok_without_touching_the_database(client: TestClient) -> None:
    # No override: if /healthz called the DB, it would fail (nothing is listening in tests).
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_is_ok_when_database_is_reachable(client: TestClient) -> None:
    client.app.dependency_overrides[database_ready] = lambda: True  # type: ignore[attr-defined]

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_is_503_when_database_is_unreachable(client: TestClient) -> None:
    client.app.dependency_overrides[database_ready] = lambda: False  # type: ignore[attr-defined]

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_shutdown_disposes_the_engine(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    disposed: list[bool] = []
    real_dispose = AsyncEngine.dispose

    async def spy_dispose(self: AsyncEngine, close: bool = True) -> None:
        disposed.append(True)
        await real_dispose(self, close)

    monkeypatch.setattr(AsyncEngine, "dispose", spy_dispose)

    with TestClient(create_app(settings)):
        assert disposed == []  # still running

    assert disposed == [True]  # graceful shutdown closed the pool
