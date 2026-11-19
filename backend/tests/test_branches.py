"""GET /branches returns the seeded branch codes (real Postgres)."""

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.factory import create_app
from app.models import Branch, BranchAlias
from tests.helpers import with_database_url

pytestmark = pytest.mark.db


def test_end_to_end_through_the_real_lifespan_and_session(
    settings: Settings, test_database_url: str
) -> None:
    # No overrides: the lifespan's engine + the real get_session serve the request.
    app = create_app(with_database_url(settings, test_database_url))
    with TestClient(app) as client:
        response = client.get("/branches")

    assert response.status_code == 200
    assert any(branch["code"] == "CSE" for branch in response.json())


@pytest.mark.anyio
async def test_lists_seeded_branches_sorted_by_code(api: httpx.AsyncClient) -> None:
    response = await api.get("/branches")  # no cookie: the endpoint is public

    assert response.status_code == 200
    body = response.json()
    codes = [branch["code"] for branch in body]
    assert codes == sorted(codes)
    assert {"code": "CSE", "name": "Computer Science and Engineering"} in body


@pytest.mark.anyio
async def test_exposes_only_code_and_name(api: httpx.AsyncClient) -> None:
    response = await api.get("/branches")

    assert all(set(branch) == {"code", "name"} for branch in response.json())


@pytest.mark.anyio
async def test_reflects_rows_in_the_database(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(Branch(code="AIML", name="AI and Machine Learning"))
    await db_session.flush()

    response = await api.get("/branches")

    assert {"code": "AIML", "name": "AI and Machine Learning"} in response.json()


@pytest.mark.anyio
async def test_seeded_aliases_are_lower_case_and_point_to_real_branches(
    db_session: AsyncSession,
) -> None:
    aliases = (await db_session.scalars(select(BranchAlias))).all()
    codes = set(await db_session.scalars(select(Branch.code)))

    assert aliases, "the seed migration should add aliases"
    assert all(alias.alias == alias.alias.lower() for alias in aliases)
    assert {alias.branch_code for alias in aliases} <= codes
