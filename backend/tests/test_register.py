"""POST /auth/register (real Postgres)."""

from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.models import User
from tests.conftest import VALID_ENV

pytestmark = [pytest.mark.anyio, pytest.mark.db]

INVITE_CODE = VALID_ENV["BATCH_INVITE_CODE"]


def payload(**overrides: Any) -> dict[str, Any]:
    return {
        "email": "Student@Example.com",
        "password": "correct horse battery",
        "name": "  Asha Rao  ",
        "invite_code": INVITE_CODE,
    } | overrides


async def count_users(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(User)) or 0


async def test_register_creates_a_student(api: httpx.AsyncClient, db_session: AsyncSession) -> None:
    response = await api.post("/auth/register", json=payload())

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "email", "name", "role"}  # never the password hash
    assert body["email"] == "student@example.com"  # stored lower-cased
    assert body["name"] == "Asha Rao"  # whitespace stripped
    assert body["role"] == "student"

    user = await db_session.scalar(select(User).where(User.email == "student@example.com"))
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")
    assert await verify_password("correct horse battery", user.password_hash)


async def test_wrong_invite_code_is_403_and_creates_nothing(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    before = await count_users(db_session)

    response = await api.post("/auth/register", json=payload(invite_code="wrong-code"))

    assert response.status_code == 403
    assert response.json() == {"detail": "Invalid invite code"}
    assert await count_users(db_session) == before


async def test_duplicate_email_is_409_even_with_different_case(api: httpx.AsyncClient) -> None:
    assert (await api.post("/auth/register", json=payload())).status_code == 201

    response = await api.post("/auth/register", json=payload(email="STUDENT@example.com"))

    assert response.status_code == 409
    assert response.json() == {"detail": "Email already registered"}


async def test_invite_code_is_checked_before_the_email(api: httpx.AsyncClient) -> None:
    # Without the invite code, nobody can find out whether an email is registered.
    assert (await api.post("/auth/register", json=payload())).status_code == 201

    response = await api.post("/auth/register", json=payload(invite_code="wrong-code"))

    assert response.status_code == 403


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "not-an-email"},
        {"password": "short"},  # under 8
        {"password": "x" * 129},  # over 128
        {"name": "   "},  # empty after stripping
        {"name": "x" * 101},
        {"invite_code": None},
        {"role": "admin"},  # unknown fields are rejected, not ignored
    ],
)
async def test_invalid_input_is_422_and_creates_nothing(
    api: httpx.AsyncClient, db_session: AsyncSession, overrides: dict[str, Any]
) -> None:
    before = await count_users(db_session)

    response = await api.post("/auth/register", json=payload(**overrides))

    assert response.status_code == 422
    assert await count_users(db_session) == before


async def test_validation_errors_do_not_echo_the_password(api: httpx.AsyncClient) -> None:
    fake_password = "Qz7#kw"  # noqa: S105 - fake test value, under the 8-char minimum
    response = await api.post("/auth/register", json=payload(password=fake_password))

    assert response.status_code == 422
    assert fake_password not in response.text
    [error] = response.json()["detail"]
    assert error["loc"] == ["body", "password"]  # still says which field and why
    assert error["type"] == "too_short"
