"""Origin check on unsafe methods (CSRF layer 2). No DB needed: POST /auth/logout without a
cookie never touches the database."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.factory import create_app

ALLOWED = "http://localhost:5173"


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_allowed_origin_passes(client: TestClient) -> None:
    response = client.post("/auth/logout", headers={"Origin": ALLOWED})

    assert response.status_code == 204


@pytest.mark.parametrize(
    "origin",
    [
        None,  # missing: fail closed
        "https://evil.example",
        "null",  # sandboxed iframes / file:// pages send this
        "http://localhost:5174",  # other port
        "https://localhost:5173",  # other scheme
        "http://localhost:5173.evil.example",  # prefix trick
    ],
)
def test_other_origins_are_403(client: TestClient, origin: str | None) -> None:
    headers = {"Origin": origin} if origin else {}

    response = client.post("/auth/logout", headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "Origin not allowed"}
    assert response.headers["x-request-id"]  # rejected requests are still traceable


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_every_unsafe_method_is_checked(client: TestClient, method: str) -> None:
    response = client.request(method, "/me", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403


def test_safe_methods_need_no_origin(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200


def test_secret_header_endpoints_are_exempt(client: TestClient) -> None:
    # No Origin header. The routes answer 401 (missing secret header), which proves the
    # Origin check let the request through; any other POST without an Origin gets 403.
    assert client.post("/internal/run-reminders").status_code == 401
    assert client.post("/telegram/webhook").status_code == 404  # Telegram off in tests
