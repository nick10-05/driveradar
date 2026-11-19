"""Linking Telegram: POST/DELETE /me/telegram-link and POST /telegram/webhook (real Postgres)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.telegram import BAD_LINK, HELP, LINKED
from app.core.config import Settings
from app.core.security import hash_session_token
from app.models import StudentProfile, User
from tests.conftest import api_client
from tests.helpers import BOT_USERNAME, WEBHOOK_SECRET, profile, sign_in

pytestmark = [pytest.mark.anyio, pytest.mark.db]

CHAT_ID = 555_000_111


@pytest.fixture
async def tg(
    telegram_settings: Settings, db_session: AsyncSession
) -> AsyncIterator[httpx.AsyncClient]:
    """A logged-in student with a profile, on a server that has a bot configured."""
    async with api_client(telegram_settings, db_session) as client:
        await sign_in(client, "tg@example.com")
        assert (await client.put("/me/profile", json=profile())).status_code == 200
        yield client


def update_body(text: str | None, chat_id: int = CHAT_ID, chat_type: str = "private") -> Any:
    message: dict[str, Any] = {
        "message_id": 1,
        "date": 0,
        "chat": {"id": chat_id, "type": chat_type},
        "from": {"id": chat_id, "is_bot": False, "first_name": "Asha"},
    }
    if text is not None:
        message["text"] = text
    return {"update_id": 1, "message": message}


async def telegram_says(
    client: httpx.AsyncClient, text: str | None, secret: str | None = WEBHOOK_SECRET, **kw: Any
) -> httpx.Response:
    """POST an update with Telegram's secret header (the webhook ignores cookies)."""
    headers = {} if secret is None else {"X-Telegram-Bot-Api-Secret-Token": secret}
    return await client.post(
        "/telegram/webhook",
        json=update_body(text, **kw),
        headers=headers,
    )


async def new_link_token(client: httpx.AsyncClient) -> str:
    response = await client.post("/me/telegram-link")
    assert response.status_code == 201, response.text
    url = response.json()["url"]
    return parse_qs(urlsplit(url).query)["start"][0]


async def profile_of(session: AsyncSession, email: str) -> StudentProfile:
    statement = select(StudentProfile).join(User).where(User.email == email)
    found = await session.scalar(statement.execution_options(populate_existing=True))
    assert found is not None
    return found


# ---------------------------------------------------------------- POST /me/telegram-link


async def test_link_is_a_deep_link_to_our_bot(tg: httpx.AsyncClient) -> None:
    before = datetime.now(UTC)

    response = await tg.post("/me/telegram-link")

    assert response.status_code == 201
    body = response.json()
    parts = urlsplit(body["url"])
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "t.me", f"/{BOT_USERNAME}")
    token = parse_qs(parts.query)["start"][0]
    assert len(token) >= 43  # 256 random bits
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert timedelta(minutes=14) < expires_at - before <= timedelta(minutes=15, seconds=5)


async def test_only_the_token_hash_is_stored(
    tg: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    token = await new_link_token(tg)

    stored = await profile_of(db_session, "tg@example.com")

    assert stored.telegram_link_token_hash == hash_session_token(token)
    assert stored.telegram_link_token_hash != token


async def test_link_needs_a_profile(telegram_settings: Settings, db_session: AsyncSession) -> None:
    async with api_client(telegram_settings, db_session) as client:
        await sign_in(client, "noprofile@example.com")

        response = await client.post("/me/telegram-link")

    assert response.status_code == 409


async def test_link_needs_login(telegram_settings: Settings, db_session: AsyncSession) -> None:
    async with api_client(telegram_settings, db_session) as client:
        assert (await client.post("/me/telegram-link")).status_code == 401


async def test_link_is_404_when_no_bot_is_configured(student: httpx.AsyncClient) -> None:
    assert (await student.post("/me/telegram-link")).status_code == 404
    assert (await student.get("/me")).json()["telegram_available"] is False


async def test_me_says_telegram_is_available(tg: httpx.AsyncClient) -> None:
    assert (await tg.get("/me")).json()["telegram_available"] is True


# ---------------------------------------------------------------- the webhook


async def test_start_with_a_valid_token_links_the_chat(
    tg: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    token = await new_link_token(tg)

    response = await telegram_says(tg, f"/start {token}")

    assert response.status_code == 200
    assert response.json() == {"method": "sendMessage", "chat_id": CHAT_ID, "text": LINKED}
    stored = await profile_of(db_session, "tg@example.com")
    assert stored.telegram_chat_id == CHAT_ID
    assert stored.telegram_link_token_hash is None  # cleared: single use
    assert (await tg.get("/me")).json()["profile"]["telegram_linked"] is True


async def test_a_token_works_only_once(tg: httpx.AsyncClient, db_session: AsyncSession) -> None:
    token = await new_link_token(tg)
    await telegram_says(tg, f"/start {token}")

    again = await telegram_says(tg, f"/start {token}", chat_id=999)

    assert again.json()["text"] == BAD_LINK
    assert (await profile_of(db_session, "tg@example.com")).telegram_chat_id == CHAT_ID


async def test_an_expired_token_is_rejected(
    tg: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    token = await new_link_token(tg)
    await db_session.execute(
        update(StudentProfile)
        .where(StudentProfile.telegram_link_token_hash == hash_session_token(token))
        .values(telegram_link_expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )

    response = await telegram_says(tg, f"/start {token}")

    assert response.json()["text"] == BAD_LINK
    assert (await profile_of(db_session, "tg@example.com")).telegram_chat_id is None


async def test_a_new_link_replaces_the_old_one(tg: httpx.AsyncClient) -> None:
    old = await new_link_token(tg)
    new = await new_link_token(tg)

    assert (await telegram_says(tg, f"/start {old}")).json()["text"] == BAD_LINK
    assert (await telegram_says(tg, f"/start {new}")).json()["text"] == LINKED


async def test_unknown_token_is_rejected(tg: httpx.AsyncClient) -> None:
    assert (await telegram_says(tg, "/start not-a-real-token")).json()["text"] == BAD_LINK


async def test_start_without_a_token_explains_what_to_do(tg: httpx.AsyncClient) -> None:
    response = await telegram_says(tg, "/start")

    assert response.json() == {"method": "sendMessage", "chat_id": CHAT_ID, "text": HELP}


async def test_start_with_bot_name_suffix_works(tg: httpx.AsyncClient) -> None:
    token = await new_link_token(tg)

    response = await telegram_says(tg, f"/start@{BOT_USERNAME} {token}")

    assert response.json()["text"] == LINKED


@pytest.mark.parametrize("text", ["hello", "/help", None])
async def test_other_messages_are_ignored_with_200(tg: httpx.AsyncClient, text: str | None) -> None:
    response = await telegram_says(tg, text)

    assert response.status_code == 200  # 2xx, or Telegram keeps retrying
    assert response.json() == {}


async def test_group_chats_are_never_linked(
    tg: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    token = await new_link_token(tg)

    response = await telegram_says(tg, f"/start {token}", chat_id=-100123, chat_type="group")

    assert response.json() == {}
    assert (await profile_of(db_session, "tg@example.com")).telegram_chat_id is None


async def test_linking_a_chat_moves_it_from_another_account(
    tg: httpx.AsyncClient, telegram_settings: Settings, db_session: AsyncSession
) -> None:
    await telegram_says(tg, f"/start {await new_link_token(tg)}")
    async with api_client(telegram_settings, db_session) as other:
        await sign_in(other, "other@example.com")
        await other.put("/me/profile", json=profile())

        response = await telegram_says(other, f"/start {await new_link_token(other)}")

    assert response.json()["text"] == LINKED
    assert (await profile_of(db_session, "other@example.com")).telegram_chat_id == CHAT_ID
    assert (await profile_of(db_session, "tg@example.com")).telegram_chat_id is None


async def test_a_bad_token_does_not_unlink_the_chat(
    tg: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await telegram_says(tg, f"/start {await new_link_token(tg)}")

    await telegram_says(tg, "/start bogus")

    assert (await profile_of(db_session, "tg@example.com")).telegram_chat_id == CHAT_ID


class TestWebhookSecret:
    @pytest.mark.parametrize("secret", [None, "", "wrong-secret-0123456789", WEBHOOK_SECRET + "x"])
    async def test_wrong_or_missing_secret_is_401(
        self, tg: httpx.AsyncClient, db_session: AsyncSession, secret: str | None
    ) -> None:
        token = await new_link_token(tg)

        response = await telegram_says(tg, f"/start {token}", secret=secret)

        assert response.status_code == 401
        assert (await profile_of(db_session, "tg@example.com")).telegram_chat_id is None

    async def test_secret_is_checked_before_the_body(self, tg: httpx.AsyncClient) -> None:
        response = await tg.post("/telegram/webhook", content=b"not json")

        assert response.status_code == 401  # not 422: no hints for callers without the secret

    async def test_no_origin_header_needed(self, tg: httpx.AsyncClient) -> None:
        response = await tg.post(
            "/telegram/webhook",
            json=update_body("hello"),
            headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET, "Origin": ""},
        )

        assert response.status_code == 200

    async def test_webhook_is_404_when_no_bot_is_configured(self, api: httpx.AsyncClient) -> None:
        response = await telegram_says(api, "/start x")

        assert response.status_code == 404


# ---------------------------------------------------------------- DELETE /me/telegram-link


async def test_disconnect_unlinks(tg: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await telegram_says(tg, f"/start {await new_link_token(tg)}")

    response = await tg.delete("/me/telegram-link")

    assert response.status_code == 204
    assert (await profile_of(db_session, "tg@example.com")).telegram_chat_id is None
    assert (await tg.get("/me")).json()["profile"]["telegram_linked"] is False


async def test_disconnect_cancels_a_pending_link(tg: httpx.AsyncClient) -> None:
    token = await new_link_token(tg)

    assert (await tg.delete("/me/telegram-link")).status_code == 204

    assert (await telegram_says(tg, f"/start {token}")).json()["text"] == BAD_LINK


async def test_disconnect_needs_origin(tg: httpx.AsyncClient) -> None:
    response = await tg.delete("/me/telegram-link", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403
