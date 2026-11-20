"""New-drive Telegram alerts on publish (real Postgres; Telegram mocked with respx).

Day 8's "done when": publishing pings eligible students.
"""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import respx
from pydantic import HttpUrl
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from app.core.config import Settings
from app.models import Notification, StudentProfile, User
from app.services.alerts import new_drive_alerts_task, send_new_drive_alerts
from app.services.telegram import TelegramClient
from tests.conftest import api_client
from tests.helpers import BOT_TOKEN, create, profile, sign_in, sign_in_as_admin

pytestmark = [pytest.mark.anyio, pytest.mark.db]

SEND_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
OK = httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
RULES = {"min_cgpa": 7.0, "allowed_branches": ["CSE", "ECE"]}


async def no_sleep(_: float) -> None:
    pass


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def telegram(http: httpx.AsyncClient) -> TelegramClient:
    return TelegramClient(http, BOT_TOKEN, sleep=no_sleep)


@pytest.fixture
async def tg_admin(
    telegram_settings: Settings, db_session: AsyncSession, telegram: TelegramClient
) -> AsyncIterator[httpx.AsyncClient]:
    settings = telegram_settings.model_copy(
        update={"app_base_url": HttpUrl("https://driveradar.example")}
    )
    async with api_client(settings, db_session, telegram=telegram) as client:
        await sign_in_as_admin(client, db_session)
        yield client


async def add_student(
    settings: Settings,
    session: AsyncSession,
    email: str,
    chat_id: int | None,
    **profile_overrides: Any,
) -> uuid.UUID:
    """A student with a profile, linked to `chat_id` (None = never linked Telegram)."""
    async with api_client(settings, session) as client:
        await sign_in(client, email)
        response = await client.put("/me/profile", json=profile(**profile_overrides))
        assert response.status_code == 200
    user_id = await session.scalar(select(User.id).where(User.email == email))
    assert user_id is not None
    if chat_id is not None:
        await session.execute(
            update(StudentProfile)
            .where(StudentProfile.user_id == user_id)
            .values(telegram_chat_id=chat_id)
        )
    return user_id


async def publish_drive(admin: httpx.AsyncClient, **overrides: Any) -> dict[str, Any]:
    drive = await create(admin, eligibility=RULES, **overrides)
    response = await admin.patch(f"/admin/drives/{drive['id']}", json={"status": "published"})
    assert response.status_code == 200, response.text
    return drive


def sent_chats(route: respx.Route) -> list[int]:
    return [json.loads(call.request.content)["chat_id"] for call in route.calls]


async def notification_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Notification)) or 0


async def chat_of(session: AsyncSession, user_id: uuid.UUID) -> int | None:
    found = await session.get(StudentProfile, user_id, populate_existing=True)
    assert found is not None
    return found.telegram_chat_id


@respx.mock
async def test_publishing_pings_only_eligible_linked_students(
    tg_admin: httpx.AsyncClient, telegram_settings: Settings, db_session: AsyncSession
) -> None:
    route = respx.post(SEND_URL).mock(return_value=OK)
    await add_student(telegram_settings, db_session, "yes@example.com", 1001)
    await add_student(telegram_settings, db_session, "ece@example.com", 1002, branch_code="ECE")
    await add_student(telegram_settings, db_session, "lowcgpa@example.com", 1003, cgpa=6.5)
    await add_student(telegram_settings, db_session, "mech@example.com", 1004, branch_code="ME")
    await add_student(telegram_settings, db_session, "unlinked@example.com", None)

    drive = await publish_drive(tg_admin, company="Acme Corp", ctc_text="12 LPA", location="Pune")

    assert sorted(sent_chats(route)) == [1001, 1002]
    text = json.loads(route.calls.last.request.content)["text"]
    assert "Acme Corp - Software Engineer" in text
    assert "CTC: 12 LPA" in text
    assert "Location: Pune" in text
    assert "IST" in text
    assert f"https://driveradar.example/drives/{drive['id']}" in text
    assert await notification_count(db_session) == 2


@respx.mock
async def test_deadline_is_shown_in_ist(
    tg_admin: httpx.AsyncClient, telegram_settings: Settings, db_session: AsyncSession
) -> None:
    route = respx.post(SEND_URL).mock(return_value=OK)
    await add_student(telegram_settings, db_session, "yes@example.com", 1001)

    await publish_drive(tg_admin, deadline="2030-12-01T11:30:00Z")

    assert (
        "Apply by: 01 Dec 2030, 05:00 PM IST"
        in json.loads(route.calls.last.request.content)["text"]
    )


@respx.mock
async def test_editing_a_published_drive_sends_nothing_new(
    tg_admin: httpx.AsyncClient, telegram_settings: Settings, db_session: AsyncSession
) -> None:
    route = respx.post(SEND_URL).mock(return_value=OK)
    await add_student(telegram_settings, db_session, "yes@example.com", 1001)
    drive = await publish_drive(tg_admin)

    response = await tg_admin.patch(
        f"/admin/drives/{drive['id']}", json={"status": "published", "location": "Pune"}
    )

    assert response.status_code == 200
    assert route.call_count == 1


@respx.mock
async def test_creating_a_draft_sends_nothing(
    tg_admin: httpx.AsyncClient, telegram_settings: Settings, db_session: AsyncSession
) -> None:
    route = respx.post(SEND_URL).mock(return_value=OK)
    await add_student(telegram_settings, db_session, "yes@example.com", 1001)

    await create(tg_admin, eligibility=RULES)

    assert route.call_count == 0


@respx.mock
async def test_running_twice_never_sends_twice(
    tg_admin: httpx.AsyncClient,
    telegram_settings: Settings,
    db_session: AsyncSession,
    telegram: TelegramClient,
) -> None:
    route = respx.post(SEND_URL).mock(return_value=OK)
    await add_student(telegram_settings, db_session, "yes@example.com", 1001)
    drive = await publish_drive(tg_admin)

    summary = await send_new_drive_alerts(
        same_session(db_session), telegram, uuid.UUID(drive["id"]), None, sleep=no_sleep
    )

    assert route.call_count == 1  # only the publish sent it
    assert (summary.eligible, summary.sent, summary.skipped) == (1, 0, 1)


@respx.mock
async def test_blocked_bot_unlinks_the_chat(
    tg_admin: httpx.AsyncClient, telegram_settings: Settings, db_session: AsyncSession
) -> None:
    respx.post(SEND_URL).mock(return_value=httpx.Response(403, json={"ok": False}))
    student = await add_student(telegram_settings, db_session, "blocked@example.com", 1001)

    await publish_drive(tg_admin)

    assert await chat_of(db_session, student) is None
    assert await notification_count(db_session) == 0  # nothing was delivered


@respx.mock
async def test_temporary_failure_keeps_the_link_and_allows_a_retry(
    tg_admin: httpx.AsyncClient,
    telegram_settings: Settings,
    db_session: AsyncSession,
    telegram: TelegramClient,
) -> None:
    route = respx.post(SEND_URL).mock(side_effect=[httpx.Response(500), OK])
    student = await add_student(telegram_settings, db_session, "flaky@example.com", 1001)
    drive = await publish_drive(tg_admin)
    assert await notification_count(db_session) == 0  # failed send = no "sent" row
    assert await chat_of(db_session, student) == 1001

    summary = await send_new_drive_alerts(
        same_session(db_session), telegram, uuid.UUID(drive["id"]), None, sleep=no_sleep
    )

    assert summary.sent == 1
    assert route.call_count == 2
    assert await notification_count(db_session) == 1


@respx.mock
async def test_one_failure_does_not_stop_the_others(
    tg_admin: httpx.AsyncClient, telegram_settings: Settings, db_session: AsyncSession
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500) if json.loads(request.content)["chat_id"] == 1001 else OK

    route = respx.post(SEND_URL).mock(side_effect=respond)
    await add_student(telegram_settings, db_session, "a@example.com", 1001)
    await add_student(telegram_settings, db_session, "b@example.com", 1002)

    await publish_drive(tg_admin)

    assert sorted(sent_chats(route)) == [1001, 1002]
    assert await notification_count(db_session) == 1


async def test_without_a_bot_publishing_still_works(
    settings: Settings, db_session: AsyncSession
) -> None:
    async with api_client(settings, db_session) as admin:  # telegram=None
        await sign_in_as_admin(admin, db_session)
        with respx.mock:  # any outbound call would fail the test (nothing is mocked)
            await publish_drive(admin)


@respx.mock
async def test_a_closed_drive_gets_no_alerts(
    tg_admin: httpx.AsyncClient,
    telegram_settings: Settings,
    db_session: AsyncSession,
    telegram: TelegramClient,
) -> None:
    route = respx.post(SEND_URL).mock(return_value=OK)
    drive = await publish_drive(tg_admin)  # nobody linked yet
    await add_student(telegram_settings, db_session, "late@example.com", 1001)
    await tg_admin.patch(f"/admin/drives/{drive['id']}", json={"status": "closed"})

    summary = await send_new_drive_alerts(
        same_session(db_session), telegram, uuid.UUID(drive["id"]), None, sleep=no_sleep
    )

    assert summary.eligible == 0
    assert route.call_count == 0


def same_session(session: AsyncSession) -> Any:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield session

    return factory


async def test_a_crash_in_the_background_task_is_logged_not_raised(
    telegram: TelegramClient,
) -> None:
    @asynccontextmanager
    async def broken_db() -> AsyncIterator[AsyncSession]:
        raise ConnectionError("database went away")
        yield  # pragma: no cover

    with capture_logs() as events:
        await new_drive_alerts_task(broken_db, telegram, uuid.uuid4(), None)

    assert [e["event"] for e in events if e["log_level"] == "error"] == ["new_drive_alerts_failed"]
