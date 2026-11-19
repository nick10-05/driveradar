"""Small helpers shared by test modules (fixtures live in conftest.py)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import SecretStr
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, normalize_database_url
from app.models import User

INVITE_CODE = "invite-code-123"  # the test environment's BATCH_INVITE_CODE
PASSWORD = "correct horse battery"  # noqa: S105 - fake test value


BOT_TOKEN = "123456:fake-bot-token-for-tests"  # noqa: S105 - fake test value
WEBHOOK_SECRET = "webhook-secret-0123456789"  # noqa: S105 - fake test value
BOT_USERNAME = "DriveRadarTestBot"


def with_telegram(settings: Settings) -> Settings:
    """A copy of settings with a (fake) Telegram bot configured."""
    return settings.model_copy(
        update={
            "telegram_bot_token": SecretStr(BOT_TOKEN),
            "telegram_webhook_secret": SecretStr(WEBHOOK_SECRET),
            "telegram_bot_username": BOT_USERNAME,
        }
    )


def with_database_url(settings: Settings, raw_url: str) -> Settings:
    """A copy of settings pointing at another database (same normalisation as load_config)."""
    url, ssl = normalize_database_url(raw_url)
    return settings.model_copy(update={"database_url": SecretStr(url), "database_ssl": ssl})


async def register(api: httpx.AsyncClient, email: str) -> None:
    body = {"email": email, "password": PASSWORD, "name": "Asha Rao", "invite_code": INVITE_CODE}
    assert (await api.post("/auth/register", json=body)).status_code == 201


async def log_in(api: httpx.AsyncClient, email: str) -> None:
    login = {"email": email, "password": PASSWORD}
    assert (await api.post("/auth/login", json=login)).status_code == 200


async def sign_in(api: httpx.AsyncClient, email: str = "asha@example.com") -> None:
    """Register + log in; the client's cookie jar then holds the session."""
    await register(api, email)
    await log_in(api, email)


async def sign_in_as_admin(
    api: httpx.AsyncClient, session: AsyncSession, email: str = "admin@example.com"
) -> None:
    """Register, promote in the DB (the only way to become admin), then log in."""
    await register(api, email)
    await session.execute(update(User).where(User.email == email).values(role="admin"))
    await log_in(api, email)


def profile(**overrides: Any) -> dict[str, Any]:
    return {"branch_code": "CSE", "cgpa": 7.5, "active_backlogs": 0, "grad_year": 2027} | overrides


# ---------------------------------------------------------------- drives (admin client)


def iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).isoformat()


def new_drive(**overrides: Any) -> dict[str, Any]:
    return {
        "company": "Acme Corp",
        "role_title": "Software Engineer",
        "deadline": iso(timedelta(days=7)),
        "raw_text": "Acme Corp is hiring Software Engineers. Apply by next week.",
    } | overrides


async def create(admin: httpx.AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await admin.post("/admin/drives", json=new_drive(**overrides))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def publish(admin: httpx.AsyncClient, **overrides: Any) -> dict[str, Any]:
    drive = await create(admin, **overrides)
    response = await admin.patch(f"/admin/drives/{drive['id']}", json={"status": "published"})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body
