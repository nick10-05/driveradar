"""Rate limits on /auth/login and /auth/register (real Postgres).

Small limits are injected so each test needs only a few requests.
"""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.rate_limit import AuthLimiters, SlidingWindowLimiter
from tests.conftest import VALID_ENV, api_client

pytestmark = [pytest.mark.anyio, pytest.mark.db]

PASSWORD = "correct horse battery"  # noqa: S105 - fake test value
INVITE = VALID_ENV["BATCH_INVITE_CODE"]


@pytest.fixture
async def api(settings: Settings, db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    limiters = AuthLimiters(
        login_email=SlidingWindowLimiter(3, 900),
        login_ip=SlidingWindowLimiter(5, 900),
        register_ip=SlidingWindowLimiter(2, 3600),
    )
    async with api_client(settings, db_session, limiters) as client:
        yield client


async def register(api: httpx.AsyncClient, email: str, **overrides: Any) -> httpx.Response:
    body = {"email": email, "password": PASSWORD, "name": "Test", "invite_code": INVITE}
    return await api.post("/auth/register", json=body | overrides)


async def login(api: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await api.post("/auth/login", json={"email": email, "password": password})


async def test_email_is_blocked_after_too_many_failures(api: httpx.AsyncClient) -> None:
    await register(api, "a@example.com")
    for _ in range(3):
        assert (await login(api, "a@example.com", "wrong password")).status_code == 401

    blocked = await login(api, "a@example.com")  # even the right password

    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many attempts. Try again later."}
    assert 1 <= int(blocked.headers["retry-after"]) <= 900
    assert "set-cookie" not in blocked.headers


async def test_block_is_per_email_and_case_insensitive(api: httpx.AsyncClient) -> None:
    await register(api, "a@example.com")
    await register(api, "b@example.com")
    for email in ("a@example.com", "A@example.com", "A@EXAMPLE.COM"):
        await login(api, email, "wrong password")

    assert (await login(api, "a@example.com")).status_code == 429
    assert (await login(api, "b@example.com")).status_code == 200


async def test_success_clears_earlier_failures(api: httpx.AsyncClient) -> None:
    await register(api, "a@example.com")
    for _ in range(2):
        await login(api, "a@example.com", "wrong password")
    assert (await login(api, "a@example.com")).status_code == 200

    for _ in range(2):  # would be failures 3 and 4 without the reset
        assert (await login(api, "a@example.com", "wrong password")).status_code == 401


async def test_ip_is_blocked_after_failures_across_many_emails(api: httpx.AsyncClient) -> None:
    for i in range(5):
        await login(api, f"guess{i}@example.com", "wrong password")

    assert (await login(api, "another@example.com")).status_code == 429


async def test_successful_logins_do_not_use_up_the_ip_limit(api: httpx.AsyncClient) -> None:
    # Many students behind one college Wi-Fi IP must all be able to log in.
    await register(api, "a@example.com")
    for _ in range(8):
        assert (await login(api, "a@example.com")).status_code == 200


async def test_wrong_invite_codes_are_limited_per_ip(api: httpx.AsyncClient) -> None:
    for i in range(2):
        assert (
            await register(api, f"x{i}@example.com", invite_code="guess-1234")
        ).status_code == 403

    blocked = await register(api, "real@example.com")  # even with the right code

    assert blocked.status_code == 429


async def test_successful_registrations_do_not_count(api: httpx.AsyncClient) -> None:
    for i in range(4):
        assert (await register(api, f"student{i}@example.com")).status_code == 201
    assert (await register(api, "student0@example.com")).status_code == 409

    assert (await register(api, "student9@example.com")).status_code == 201


async def test_invalid_input_does_not_count(api: httpx.AsyncClient) -> None:
    await register(api, "a@example.com")
    for _ in range(5):
        assert (await api.post("/auth/login", json={"email": "bad"})).status_code == 422

    assert (await login(api, "a@example.com")).status_code == 200
