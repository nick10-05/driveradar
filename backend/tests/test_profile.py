"""PUT /me/profile and the profile in GET /me (real Postgres)."""

from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import StudentProfile
from tests.helpers import profile, sign_in

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def test_me_has_no_profile_until_one_is_saved(api: httpx.AsyncClient) -> None:
    await sign_in(api)

    body = (await api.get("/me")).json()

    assert body["profile"] is None
    assert set(body) == {"id", "email", "name", "role", "profile"}


async def test_save_profile_then_read_it_back(api: httpx.AsyncClient) -> None:
    await sign_in(api)

    response = await api.put("/me/profile", json=profile(branch_code=" cse ", cgpa=8.25))

    assert response.status_code == 200
    expected = {
        "branch_code": "CSE",  # trimmed + upper-cased
        "cgpa": 8.25,  # a JSON number, not a string
        "active_backlogs": 0,
        "grad_year": 2027,
        "telegram_linked": False,
    }
    assert response.json() == expected
    assert (await api.get("/me")).json()["profile"] == expected


async def test_saving_again_replaces_the_profile(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await sign_in(api)
    await api.put("/me/profile", json=profile())

    response = await api.put("/me/profile", json=profile(branch_code="ECE", active_backlogs=2))

    assert response.json()["branch_code"] == "ECE"
    assert response.json()["active_backlogs"] == 2
    assert await db_session.scalar(select(func.count()).select_from(StudentProfile)) == 1


async def test_cgpa_is_stored_exactly(api: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await sign_in(api)
    await api.put("/me/profile", json=profile(cgpa="7.10"))

    stored = await db_session.scalar(select(StudentProfile.cgpa))

    assert stored == Decimal("7.10")


async def test_saving_never_touches_telegram_fields(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await sign_in(api)
    await api.put("/me/profile", json=profile())
    await db_session.execute(update(StudentProfile).values(telegram_chat_id=12345))

    response = await api.put("/me/profile", json=profile(cgpa=9))

    assert response.json()["telegram_linked"] is True
    assert await db_session.scalar(select(StudentProfile.telegram_chat_id)) == 12345


async def test_each_user_only_changes_their_own_profile(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await sign_in(api, "first@example.com")
    await api.put("/me/profile", json=profile(branch_code="CSE"))
    api.cookies.clear()
    await sign_in(api, "second@example.com")

    await api.put("/me/profile", json=profile(branch_code="ME"))

    codes = sorted((await db_session.scalars(select(StudentProfile.branch_code))).all())
    assert codes == ["CSE", "ME"]


async def test_unknown_branch_is_422(api: httpx.AsyncClient) -> None:
    await sign_in(api)

    response = await api.put("/me/profile", json=profile(branch_code="NOPE"))

    assert response.status_code == 422
    assert response.json() == {"detail": "Unknown branch code"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"cgpa": 10.01},
        {"cgpa": -1},
        {"cgpa": 7.123},  # more than 2 decimals
        {"active_backlogs": -1},
        {"grad_year": 1999},
        {"branch_code": "  "},
        {"telegram_chat_id": 1},  # not settable here
    ],
)
async def test_invalid_values_are_422(api: httpx.AsyncClient, overrides: dict[str, Any]) -> None:
    await sign_in(api)

    response = await api.put("/me/profile", json=profile(**overrides))

    assert response.status_code == 422


async def test_profile_needs_login(api: httpx.AsyncClient) -> None:
    assert (await api.put("/me/profile", json=profile())).status_code == 401
