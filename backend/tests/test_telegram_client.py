"""TelegramClient over HTTP, with respx standing in for api.telegram.org (never the real one)."""

import json
import logging
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from app.api.deps import get_session_factory, get_telegram
from app.core.config import Settings
from app.core.logging import configure_logging
from app.services.telegram import SendResult, TelegramClient
from tests.helpers import BOT_TOKEN, with_telegram

pytestmark = pytest.mark.anyio

SEND_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
OK = httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})


def rate_limited(seconds: int) -> httpx.Response:
    body = {"ok": False, "error_code": 429, "parameters": {"retry_after": seconds}}
    return httpx.Response(429, json=body)


class FakeSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@respx.mock
async def test_sends_plain_text_without_link_previews(http: httpx.AsyncClient) -> None:
    route = respx.post(SEND_URL).mock(return_value=OK)

    result = await TelegramClient(http, BOT_TOKEN).send_message(42, "Acme *Corp* <b>")

    assert result is SendResult.SENT
    body = json.loads(route.calls.last.request.content)
    assert body["chat_id"] == 42
    assert body["text"] == "Acme *Corp* <b>"  # sent as-is
    assert "parse_mode" not in body  # plain text: no Markdown/HTML injection from notices
    assert body["link_preview_options"] == {"is_disabled": True}


@respx.mock
async def test_403_means_blocked(http: httpx.AsyncClient) -> None:
    respx.post(SEND_URL).mock(return_value=httpx.Response(403, json={"ok": False}))

    assert await TelegramClient(http, BOT_TOKEN).send_message(42, "hi") is SendResult.BLOCKED


@respx.mock
async def test_429_waits_retry_after_then_sends(http: httpx.AsyncClient) -> None:
    route = respx.post(SEND_URL).mock(side_effect=[rate_limited(3), OK])
    sleep = FakeSleep()

    result = await TelegramClient(http, BOT_TOKEN, sleep=sleep).send_message(42, "hi")

    assert result is SendResult.SENT
    assert sleep.calls == [3.0]
    assert route.call_count == 2


@respx.mock
async def test_429_twice_gives_up(http: httpx.AsyncClient) -> None:
    route = respx.post(SEND_URL).mock(side_effect=[rate_limited(1), rate_limited(1)])
    sleep = FakeSleep()

    result = await TelegramClient(http, BOT_TOKEN, sleep=sleep).send_message(42, "hi")

    assert result is SendResult.FAILED
    assert route.call_count == 2  # exactly one retry


@respx.mock
async def test_429_with_a_long_wait_is_not_retried(http: httpx.AsyncClient) -> None:
    route = respx.post(SEND_URL).mock(return_value=rate_limited(120))
    sleep = FakeSleep()

    result = await TelegramClient(http, BOT_TOKEN, sleep=sleep).send_message(42, "hi")

    assert result is SendResult.FAILED
    assert sleep.calls == []
    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(400, json={"ok": False, "description": "chat not found"}),
        httpx.Response(429, text="not json"),
    ],
)
async def test_other_errors_fail(http: httpx.AsyncClient, response: httpx.Response) -> None:
    respx.post(SEND_URL).mock(return_value=response)

    assert await TelegramClient(http, BOT_TOKEN).send_message(42, "hi") is SendResult.FAILED


@respx.mock
async def test_network_error_fails_without_raising(http: httpx.AsyncClient) -> None:
    respx.post(SEND_URL).mock(side_effect=httpx.ConnectTimeout("timed out"))

    assert await TelegramClient(http, BOT_TOKEN).send_message(42, "hi") is SendResult.FAILED


@respx.mock
async def test_set_webhook_sends_url_secret_and_allowed_updates(http: httpx.AsyncClient) -> None:
    route = respx.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True})
    )

    result = await TelegramClient(http, BOT_TOKEN).set_webhook("https://x/telegram/webhook", "s3")

    assert result == {"ok": True, "result": True}
    body = json.loads(route.calls.last.request.content)
    assert body["url"] == "https://x/telegram/webhook"
    assert body["secret_token"] == "s3"  # noqa: S105
    assert body["allowed_updates"] == ["message"]


class TestTokenNeverLogged:
    @respx.mock
    async def test_our_log_events_never_contain_the_token(self, http: httpx.AsyncClient) -> None:
        respx.post(SEND_URL).mock(side_effect=[rate_limited(1), httpx.Response(500)])
        client = TelegramClient(http, BOT_TOKEN, sleep=FakeSleep())

        with capture_logs() as events:
            await client.send_message(42, "hi")

        assert events  # something was logged (rate limit + failure)...
        assert BOT_TOKEN not in repr(events)  # ...but never the token

    def test_httpx_request_logging_is_off(self, settings: Settings) -> None:
        # httpx logs "HTTP Request: POST https://api.telegram.org/bot<token>/..." at INFO.
        configure_logging(settings)

        assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
        assert not logging.getLogger("httpcore").isEnabledFor(logging.INFO)
        assert not logging.getLogger("httpx2").isEnabledFor(logging.INFO)
        assert not logging.getLogger("httpcore2").isEnabledFor(logging.INFO)


class TestDependencies:
    """The real (non-overridden) dependencies: API tests always replace these."""

    def request_with(self, **state: object) -> Any:
        return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**state)))

    def test_no_client_when_telegram_is_off(self, settings: Settings) -> None:
        assert get_telegram(self.request_with(), settings) is None

    async def test_client_uses_the_shared_http_client(
        self, settings: Settings, http: httpx.AsyncClient
    ) -> None:
        client = get_telegram(self.request_with(http_client=http), with_telegram(settings))

        assert isinstance(client, TelegramClient)
        assert client._http is http  # one pooled client for all outbound calls

    def test_session_factory_is_the_app_sessionmaker(self) -> None:
        sessionmaker = object()

        assert get_session_factory(self.request_with(sessionmaker=sessionmaker)) is sessionmaker
