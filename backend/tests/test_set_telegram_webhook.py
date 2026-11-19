"""app.scripts.set_telegram_webhook (Telegram mocked with respx)."""

import json

import httpx
import pytest
import respx

from app.scripts.set_telegram_webhook import register, webhook_url
from tests.helpers import BOT_TOKEN, WEBHOOK_SECRET

pytestmark = pytest.mark.anyio

SET_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"


@pytest.mark.parametrize(
    "given",
    [
        "https://driveradar-api.onrender.com",
        "https://driveradar-api.onrender.com/",
        " https://driveradar-api.onrender.com/x ",
    ],
)
def test_webhook_url_points_at_our_route(given: str) -> None:
    assert webhook_url(given) == "https://driveradar-api.onrender.com/telegram/webhook"


@pytest.mark.parametrize("given", ["http://example.com", "example.com", ""])
def test_webhook_url_must_be_https(given: str) -> None:
    with pytest.raises(ValueError, match="https"):
        webhook_url(given)


@respx.mock
async def test_register_sends_secret_and_reports_success() -> None:
    route = respx.post(SET_URL).mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True})
    )
    async with httpx.AsyncClient() as http:
        message = await register(http, BOT_TOKEN, WEBHOOK_SECRET, "https://api.example.com")

    assert message == "Webhook set: https://api.example.com/telegram/webhook"
    assert json.loads(route.calls.last.request.content)["secret_token"] == WEBHOOK_SECRET
    assert BOT_TOKEN not in message and WEBHOOK_SECRET not in message


@respx.mock
async def test_register_reports_telegrams_refusal() -> None:
    respx.post(SET_URL).mock(
        return_value=httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
    )
    async with httpx.AsyncClient() as http:
        message = await register(http, BOT_TOKEN, WEBHOOK_SECRET, "https://api.example.com")

    assert message == "Telegram refused: Unauthorized"
