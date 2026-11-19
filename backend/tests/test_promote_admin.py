"""app.scripts.promote_admin (real Postgres)."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.scripts.promote_admin import _main, promote

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def test_promote_makes_the_user_an_admin(db_session: AsyncSession) -> None:
    fake_hash = "not-a-real-hash"
    db_session.add(User(email="asha@example.com", password_hash=fake_hash, name="Asha"))
    await db_session.flush()

    assert await promote(db_session, "  Asha@Example.com ") is True  # same normalisation

    role = await db_session.scalar(select(User.role).where(User.email == "asha@example.com"))
    assert role == "admin"


async def test_promote_unknown_email_returns_false(db_session: AsyncSession) -> None:
    assert await promote(db_session, "nobody@example.com") is False


async def test_cli_exits_1_for_an_unknown_email(
    test_database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Uses its own connection and commits, so only a no-op case is run here.
    monkeypatch.setenv("DATABASE_URL", test_database_url)

    assert await _main("nobody@example.com") == 1
    assert "No user with that email" in capsys.readouterr().out
