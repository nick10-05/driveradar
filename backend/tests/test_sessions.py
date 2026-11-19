"""Login, logout, GET /me and the session cookie (real Postgres)."""

from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import hash_session_token
from app.models import User, UserSession
from app.services import auth as auth_service
from tests.conftest import VALID_ENV, api_client

pytestmark = [pytest.mark.anyio, pytest.mark.db]

EMAIL = "asha@example.com"
PASSWORD = "correct horse battery"  # noqa: S105 - fake test value
COOKIE = "__Host-session"


async def register(api: httpx.AsyncClient, email: str = EMAIL) -> None:
    response = await api.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Asha Rao",
            "invite_code": VALID_ENV["BATCH_INVITE_CODE"],
        },
    )
    assert response.status_code == 201


async def login(api: httpx.AsyncClient, **overrides: Any) -> httpx.Response:
    return await api.post("/auth/login", json={"email": EMAIL, "password": PASSWORD} | overrides)


def cookie_header(response: httpx.Response) -> str:
    [header] = response.headers.get_list("set-cookie")
    return header


async def session_count(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(UserSession)) or 0


async def test_login_sets_a_hardened_session_cookie(api: httpx.AsyncClient) -> None:
    await register(api)

    response = await login(api)

    assert response.status_code == 200
    assert response.json()["email"] == EMAIL
    header = cookie_header(response).lower()
    assert header.startswith(f"{COOKIE.lower()}=")
    for flag in ("httponly", "secure", "samesite=lax", "path=/", "max-age=604800"):
        assert flag in header
    assert "domain=" not in header  # required by the __Host- prefix


async def test_db_stores_only_the_token_hash(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await register(api)
    token = (await login(api)).cookies[COOKIE]

    stored = (await db_session.scalars(select(UserSession.token_hash))).all()

    assert stored == [hash_session_token(token)]
    assert token not in stored
    assert len(token) >= 43  # 256 random bits, URL-safe base64


async def test_me_works_with_the_cookie_and_is_401_without(api: httpx.AsyncClient) -> None:
    await register(api)
    assert (await api.get("/me")).status_code == 401

    await login(api)
    response = await api.get("/me")

    assert response.status_code == 200
    assert response.json()["email"] == EMAIL


async def test_login_email_is_case_insensitive(api: httpx.AsyncClient) -> None:
    await register(api)

    assert (await login(api, email="ASHA@Example.com")).status_code == 200


@pytest.mark.parametrize(
    "overrides",
    [{"password": "wrong password"}, {"email": "nobody@example.com"}],
    ids=["wrong-password", "unknown-email"],
)
async def test_bad_credentials_get_one_generic_401(
    api: httpx.AsyncClient, db_session: AsyncSession, overrides: dict[str, str]
) -> None:
    await register(api)

    response = await login(api, **overrides)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}
    assert "set-cookie" not in response.headers
    assert await session_count(db_session) == 0


async def test_unknown_email_still_spends_a_password_check(
    api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Timing tests are flaky, so prove the dummy Argon2 check runs instead.
    calls: list[str] = []
    real = auth_service.burn_password_check_time

    async def spy(password: str) -> None:
        calls.append(password)
        await real(password)

    monkeypatch.setattr(auth_service, "burn_password_check_time", spy)

    await login(api, email="nobody@example.com")

    assert calls == [PASSWORD]


async def test_logout_deletes_the_session_and_clears_the_cookie(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await register(api)
    token = (await login(api)).cookies[COOKIE]

    response = await api.post("/auth/logout")

    assert response.status_code == 204
    assert "max-age=0" in cookie_header(response).lower()
    assert await session_count(db_session) == 0
    # The old token is dead server-side, even if someone kept a copy of it.
    api.cookies.set(COOKIE, token)
    assert (await api.get("/me")).status_code == 401


async def test_logout_without_a_session_is_still_204(api: httpx.AsyncClient) -> None:
    assert (await api.post("/auth/logout")).status_code == 204


async def test_expired_session_is_rejected(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await register(api)
    await login(api)
    await db_session.execute(update(UserSession).values(expires_at=func.now()))

    assert (await api.get("/me")).status_code == 401


async def test_forged_token_is_rejected(api: httpx.AsyncClient) -> None:
    api.cookies.set(COOKIE, "made-up-token")

    assert (await api.get("/me")).status_code == 401


async def test_login_again_replaces_this_browsers_session(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await register(api)
    first = (await login(api)).cookies[COOKIE]

    second = (await login(api)).cookies[COOKIE]

    assert first != second  # always a fresh token (no session fixation)
    assert await session_count(db_session) == 1


async def test_two_browsers_get_independent_sessions(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await register(api)
    phone = (await login(api)).cookies[COOKIE]
    api.cookies.clear()
    laptop = (await login(api)).cookies[COOKIE]

    assert await session_count(db_session) == 2
    for token in (phone, laptop):
        api.cookies.clear()
        api.cookies.set(COOKIE, token)
        assert (await api.get("/me")).status_code == 200


async def test_deleted_user_loses_access(api: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await register(api)
    await login(api)
    user = await db_session.scalar(select(User).where(User.email == EMAIL))
    assert user is not None
    await db_session.delete(user)
    await db_session.flush()

    assert (await api.get("/me")).status_code == 401


async def test_dev_insecure_mode_uses_a_plain_cookie(
    settings: Settings, db_session: AsyncSession
) -> None:
    dev = settings.model_copy(update={"environment": "dev", "session_cookie_secure": False})
    async with api_client(dev, db_session) as client:
        await register(client)

        response = await login(client)

    header = cookie_header(response).lower()
    assert header.startswith("session=")
    assert "secure" not in header
    assert "httponly" in header
