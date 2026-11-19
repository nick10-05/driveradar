"""Tell Telegram where to send bot updates (run once per backend URL, from a laptop).

    TELEGRAM_BOT_TOKEN=... TELEGRAM_WEBHOOK_SECRET=... \\
        uv run python -m app.scripts.set_telegram_webhook https://driveradar-api.onrender.com

Use the same token and secret as the Render service. Only those two variables are needed
(not the whole app config). Running it again is harmless (it replaces the old webhook).

Interview notes:
- Webhook, not polling: Telegram POSTs each update to us, so a free instance that sleeps
  just wakes up on the request (Telegram retries if it's slow). Polling would need an
  always-on process.
- The backend URL (Render) is used, not the Vercel /api proxy: Telegram is a server, so
  the same-origin cookie problem the proxy solves doesn't apply.
- The secret is registered here and Telegram sends it back on every update; the webhook
  rejects anything without it (app/api/telegram.py).
"""

import asyncio
import os
import sys
from urllib.parse import urlsplit

import httpx

from app.services.telegram import TelegramClient

WEBHOOK_PATH = "/telegram/webhook"


def webhook_url(backend_url: str) -> str:
    parts = urlsplit(backend_url.strip())
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError("Telegram only calls https:// URLs, e.g. https://x.onrender.com")
    return f"https://{parts.netloc}{WEBHOOK_PATH}"


async def register(http: httpx.AsyncClient, token: str, secret: str, backend_url: str) -> str:
    """Returns a one-line result for the terminal (never includes the token or secret)."""
    url = webhook_url(backend_url)
    result = await TelegramClient(http, token).set_webhook(url, secret)
    if result.get("ok"):
        return f"Webhook set: {url}"
    return f"Telegram refused: {result.get('description', 'unknown error')}"


async def _main(backend_url: str) -> int:  # pragma: no cover - thin CLI wrapper
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    secret = os.environ["TELEGRAM_WEBHOOK_SECRET"]
    async with httpx.AsyncClient() as http:
        message = await register(http, token, secret, backend_url)
    print(message)
    return 0 if message.startswith("Webhook set") else 1


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    needed = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET")
    if len(sys.argv) != 2 or any(name not in os.environ for name in needed):
        sys.exit(
            "usage: TELEGRAM_BOT_TOKEN=... TELEGRAM_WEBHOOK_SECRET=... "
            "python -m app.scripts.set_telegram_webhook https://<backend-host>"
        )
    sys.exit(asyncio.run(_main(sys.argv[1])))
