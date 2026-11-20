"""Deadline reminders + POST /internal/run-reminders (real Postgres; Telegram mocked).

Day 9's "done when": running the cron twice sends one message.
"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import hash_session_token
from app.models import Application, Notification, StudentProfile, User, UserSession
from app.services.reminders import reminder_heading, reminder_kind, run_reminders
from app.services.telegram import TelegramClient
from tests.conftest import VALID_ENV, api_client
from tests.helpers import BOT_TOKEN, create, iso, profile, sign_in, sign_in_as_admin

SEND_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
OK = httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
CRON = {"X-Cron-Secret": VALID_ENV["CRON_SECRET"]}
RULES = {"min_cgpa": 7.0}


async def no_sleep(_: float) -> None:
    pass


# ---------------------------------------------------------------- pure: which reminder is due

NOW = datetime(2026, 11, 20, 6, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("left", "expected"),
    [
        (timedelta(hours=30), None),
        (timedelta(hours=24, seconds=1), None),
        (timedelta(hours=24), "deadline_24h"),  # window edges are inclusive
        (timedelta(hours=3, seconds=1), "deadline_24h"),
        (timedelta(hours=3), "deadline_3h"),
        (timedelta(minutes=1), "deadline_3h"),
        (timedelta(0), None),  # closed now
        (timedelta(hours=-1), None),
    ],
)
def test_reminder_kind_uses_windows(left: timedelta, expected: str | None) -> None:
    assert reminder_kind(NOW + left, NOW) == expected


@pytest.mark.parametrize(
    ("left", "text"),
    [
        (timedelta(hours=23, minutes=10), "closes in under 24 hours"),
        (timedelta(minutes=40), "closes in under 1 hour"),
        (timedelta(hours=2, minutes=1), "closes in under 3 hours"),
    ],
)
def test_reminder_heading_rounds_up(left: timedelta, text: str) -> None:
    assert text in reminder_heading(NOW + left, NOW)


# ---------------------------------------------------------------- with a database

db = [pytest.mark.anyio, pytest.mark.db]


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def telegram(http: httpx.AsyncClient) -> TelegramClient:
    return TelegramClient(http, BOT_TOKEN, sleep=no_sleep)


@pytest.fixture
async def cron(
    telegram_settings: Settings, db_session: AsyncSession, telegram: TelegramClient
) -> AsyncIterator[httpx.AsyncClient]:
    """An admin client on a server with a bot. Students are linked *after* drives are
    published, so the only Telegram calls in these tests are reminders."""
    async with api_client(telegram_settings, db_session, telegram=telegram) as client:
        await sign_in_as_admin(client, db_session)
        yield client


async def add_student(
    settings: Settings, session: AsyncSession, email: str, chat_id: int | None, **overrides: Any
) -> uuid.UUID:
    async with api_client(settings, session) as client:
        await sign_in(client, email)
        assert (await client.put("/me/profile", json=profile(**overrides))).status_code == 200
    user_id = await session.scalar(select(User.id).where(User.email == email))
    assert user_id is not None
    if chat_id is not None:
        await session.execute(
            update(StudentProfile)
            .where(StudentProfile.user_id == user_id)
            .values(telegram_chat_id=chat_id)
        )
    return user_id


async def open_drive(admin: httpx.AsyncClient, closes_in: timedelta, **overrides: Any) -> uuid.UUID:
    drive = await create(admin, deadline=iso(closes_in), eligibility=RULES, **overrides)
    response = await admin.patch(f"/admin/drives/{drive['id']}", json={"status": "published"})
    assert response.status_code == 200, response.text
    return uuid.UUID(drive["id"])


async def run_cron(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.post("/internal/run-reminders", headers=CRON)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def sent(route: respx.Route) -> list[dict[str, Any]]:
    return [json.loads(call.request.content) for call in route.calls]


async def kinds(session: AsyncSession) -> list[str]:
    return sorted((await session.scalars(select(Notification.kind))).all())


@pytest.mark.anyio
@pytest.mark.db
@respx.mock
async def test_running_the_cron_twice_sends_one_message(
    cron: httpx.AsyncClient, telegram_settings: Settings, db_session: AsyncSession
) -> None:
    route = respx.post(SEND_URL).mock(return_value=OK)
    await open_drive(cron, timedelta(hours=20), company="Globex")
    await add_student(telegram_settings, db_session, "s@example.com", 2001)

    first = await run_cron(cron)
    second = await run_cron(cron)

    assert route.call_count == 1
    assert sent(route)[0]["chat_id"] == 2001
    assert "closes in under 20 hours" in sent(route)[0]["text"]
    assert "Globex" in sent(route)[0]["text"]
    assert first["reminders"]["deadline_24h"]["sent"] == 1
    assert second["reminders"]["deadline_24h"] == {
        "eligible": 0,
        "sent": 0,
        "skipped": 1,
        "failed": 0,
        "blocked": 0,
    }


@pytest.mark.anyio
@pytest.mark.db
@respx.mock
async def test_inside_3h_only_the_3h_reminder_is_sent(
    cron: httpx.AsyncClient, telegram_settings: Settings, db_session: AsyncSession
) -> None:
    route = respx.post(SEND_URL).mock(return_value=OK)
    await open_drive(cron, timedelta(hours=2))
    await add_student(telegram_settings, db_session, "s@example.com", 2001)

    await run_cron(cron)

    assert route.call_count == 1
    assert await kinds(db_session) == ["deadline_3h"]


@pytest.mark.anyio
@pytest.mark.db
@respx.mock
async def test_24h_then_3h_as_the_deadline_gets_closer(
    cron: httpx.AsyncClient,
    telegram_settings: Settings,
    db_session: AsyncSession,
    telegram: TelegramClient,
) -> None:
    route = respx.post(SEND_URL).mock(return_value=OK)
    await open_drive(cron, timedelta(hours=20))
    await add_student(telegram_settings, db_session, "s@example.com", 2001)
    await run_cron(cron)

    # 18 h later the same drive is inside the 3 h window.
    later = datetime.now(UTC) + timedelta(hours=18)
    summary = await run_reminders(db_session, telegram, None, now=later, sleep=no_sleep)

    assert summary.deadline_3h.sent == 1
    assert route.call_count == 2
    assert await kinds(db_session) == ["deadline_24h", "deadline_3h"]


@pytest.mark.anyio
@pytest.mark.db
@respx.mock
async def test_drives_further_than_24h_get_nothing(
    cron: httpx.AsyncClient, telegram_settings: Settings, db_session: AsyncSession
) -> None:
    route = respx.post(SEND_URL).mock(return_value=OK)
    await open_drive(cron, timedelta(hours=30))
    await add_student(telegram_settings, db_session, "s@example.com", 2001)

    body = await run_cron(cron)

    assert body["reminders"]["drives"] == 0
    assert route.call_count == 0


@pytest.mark.anyio
@pytest.mark.db
@respx.mock
async def test_who_gets_a_reminder(
    cron: httpx.AsyncClient, telegram_settings: Settings, db_session: AsyncSession
) -> None:
    route = respx.post(SEND_URL).mock(return_value=OK)
    drive_id = await open_drive(cron, timedelta(hours=10))
    statuses = {
        3001: None,  # never tracked it -> reminded
        3002: "interested",  # -> reminded
        3003: "applied",
        3004: "interview",
        3005: "withdrawn",
        3006: "rejected",
    }
    for chat_id, status in statuses.items():
        student = await add_student(
            telegram_settings, db_session, f"{chat_id}@example.com", chat_id
        )
        if status is not None:
            db_session.add(Application(student_id=student, drive_id=drive_id, status=status))
    await add_student(telegram_settings, db_session, "low@example.com", 3007, cgpa=6.0)
    await add_student(telegram_settings, db_session, "unlinked@example.com", None)
    await db_session.flush()

    await run_cron(cron)

    assert sorted(message["chat_id"] for message in sent(route)) == [3001, 3002]


@pytest.mark.anyio
@pytest.mark.db
@respx.mock
async def test_closed_drives_get_nothing(
    cron: httpx.AsyncClient, telegram_settings: Settings, db_session: AsyncSession
) -> None:
    route = respx.post(SEND_URL).mock(return_value=OK)
    drive_id = await open_drive(cron, timedelta(hours=5))
    await cron.patch(f"/admin/drives/{drive_id}", json={"status": "closed"})
    await add_student(telegram_settings, db_session, "s@example.com", 2001)

    await run_cron(cron)

    assert route.call_count == 0


@pytest.mark.anyio
@pytest.mark.db
@respx.mock
async def test_a_failed_send_is_retried_by_the_next_run(
    cron: httpx.AsyncClient, telegram_settings: Settings, db_session: AsyncSession
) -> None:
    route = respx.post(SEND_URL).mock(side_effect=[httpx.Response(500), OK])
    await open_drive(cron, timedelta(hours=5))
    await add_student(telegram_settings, db_session, "s@example.com", 2001)

    first = await run_cron(cron)
    second = await run_cron(cron)

    assert first["reminders"]["deadline_24h"]["failed"] == 1
    assert second["reminders"]["deadline_24h"]["sent"] == 1
    assert route.call_count == 2


@pytest.mark.anyio
@pytest.mark.db
@respx.mock
async def test_blocked_bot_unlinks_and_stops(
    cron: httpx.AsyncClient, telegram_settings: Settings, db_session: AsyncSession
) -> None:
    route = respx.post(SEND_URL).mock(return_value=httpx.Response(403, json={"ok": False}))
    await open_drive(cron, timedelta(hours=5))
    student = await add_student(telegram_settings, db_session, "s@example.com", 2001)

    await run_cron(cron)
    await run_cron(cron)

    assert route.call_count == 1  # unlinked after the first 403
    found = await db_session.get(StudentProfile, student, populate_existing=True)
    assert found is not None and found.telegram_chat_id is None


# ---------------------------------------------------------------- the endpoint itself


class TestCronEndpoint:
    pytestmark = db

    @pytest.mark.parametrize(
        "secret", [None, "", "wrong-cron-secret-000", VALID_ENV["CRON_SECRET"] + "x"]
    )
    async def test_wrong_or_missing_secret_is_401(
        self, api: httpx.AsyncClient, secret: str | None
    ) -> None:
        headers = {} if secret is None else {"X-Cron-Secret": secret}

        response = await api.post("/internal/run-reminders", headers=headers)

        assert response.status_code == 401

    async def test_no_origin_needed(self, api: httpx.AsyncClient) -> None:
        response = await api.post("/internal/run-reminders", headers={**CRON, "Origin": ""})

        assert response.status_code == 200

    async def test_a_logged_in_admin_cannot_run_it_without_the_secret(
        self, admin: httpx.AsyncClient
    ) -> None:
        assert (await admin.post("/internal/run-reminders")).status_code == 401

    async def test_without_a_bot_it_only_cleans_up(self, api: httpx.AsyncClient) -> None:
        body = await run_cron(api)

        assert body["telegram_enabled"] is False
        assert body["reminders"] is None

    async def test_hidden_from_openapi(self, api: httpx.AsyncClient) -> None:
        paths = (await api.get("/openapi.json")).json()["paths"]

        assert "/internal/run-reminders" not in paths
        assert "/telegram/webhook" not in paths


class TestCleanup:
    pytestmark = db

    async def test_deletes_expired_sessions_only(
        self, api: httpx.AsyncClient, db_session: AsyncSession
    ) -> None:
        await sign_in(api, "cleanup@example.com")  # one live session (the client's)
        user_id = await db_session.scalar(
            select(User.id).where(User.email == "cleanup@example.com")
        )
        db_session.add(
            UserSession(
                user_id=user_id,
                token_hash=hash_session_token("old-token"),
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await db_session.flush()

        body = await run_cron(api)

        assert body["expired_sessions_deleted"] == 1
        remaining = await db_session.scalar(
            select(func.count()).select_from(UserSession).where(UserSession.user_id == user_id)
        )
        assert remaining == 1
        assert (await api.get("/me")).status_code == 200  # still logged in

    async def test_clears_expired_link_tokens_only(
        self, api: httpx.AsyncClient, telegram_settings: Settings, db_session: AsyncSession
    ) -> None:
        old = await add_student(telegram_settings, db_session, "old@example.com", None)
        fresh = await add_student(telegram_settings, db_session, "fresh@example.com", None)
        for user_id, expires in ((old, -1), (fresh, 10)):
            await db_session.execute(
                update(StudentProfile)
                .where(StudentProfile.user_id == user_id)
                .values(
                    telegram_link_token_hash=hash_session_token(str(user_id)),
                    telegram_link_expires_at=datetime.now(UTC) + timedelta(minutes=expires),
                )
            )

        body = await run_cron(api)

        assert body["expired_link_tokens_cleared"] == 1
        fresh_profile = await db_session.get(StudentProfile, fresh, populate_existing=True)
        old_profile = await db_session.get(StudentProfile, old, populate_existing=True)
        assert fresh_profile is not None and fresh_profile.telegram_link_token_hash is not None
        assert old_profile is not None and old_profile.telegram_link_token_hash is None
