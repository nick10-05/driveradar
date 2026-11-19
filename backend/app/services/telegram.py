"""Telegram Bot API over plain httpx (DESIGN §5 F5). No bot framework.

Interview notes:
- Three methods are all we need: sendMessage, setWebhook, and reading updates (Telegram
  POSTs them to our webhook). A framework would bring polling loops, handlers and its own
  HTTP stack for that.
- Messages are plain text (no parse_mode). Company names come from notices; with Markdown
  or HTML on, a "*" or "<" in a name could break the message or inject formatting/links.
- The bot token is part of the URL (Telegram's design), so URLs are never logged (httpx's
  own request log is set to WARNING in core/logging.py) and errors log only the outcome.
- 429: Telegram says how long to wait (parameters.retry_after). We wait that long once
  (capped) and try again; still limited = give up and report it.
- 403 means the user blocked the bot (or deleted the chat). The caller unlinks them so
  we stop trying.
"""

import asyncio
import enum
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

API = "https://api.telegram.org"
TIMEOUT = httpx.Timeout(10.0)
MAX_RETRY_AFTER = 30.0  # seconds; longer waits aren't worth holding a task for


class SendResult(enum.Enum):
    SENT = "sent"
    BLOCKED = "blocked"  # 403: unlink this chat
    FAILED = "failed"  # temporary (network, 5xx, still rate-limited): may retry later


class TelegramClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        token: str,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._http = http
        self._base = f"{API}/bot{token}"
        self._sleep = sleep  # injectable, so tests don't really wait on a 429

    async def send_message(self, chat_id: int, text: str) -> SendResult:
        body = {"chat_id": chat_id, "text": text, "link_preview_options": {"is_disabled": True}}
        for attempt in (1, 2):
            try:
                response = await self._http.post(
                    f"{self._base}/sendMessage", json=body, timeout=TIMEOUT
                )
            except httpx.HTTPError as exc:
                log.warning("telegram_send_failed", reason=type(exc).__name__)
                return SendResult.FAILED
            if response.status_code == 200:
                return SendResult.SENT
            if response.status_code == 403:
                log.info("telegram_chat_blocked")
                return SendResult.BLOCKED
            if response.status_code == 429 and attempt == 1:
                wait = _retry_after(response)
                if wait is not None and wait <= MAX_RETRY_AFTER:
                    log.info("telegram_rate_limited", retry_after=wait)
                    await self._sleep(wait)
                    continue
            log.warning("telegram_send_failed", status=response.status_code)
            return SendResult.FAILED
        return SendResult.FAILED  # pragma: no cover - the loop always returns

    async def set_webhook(self, url: str, secret: str) -> dict[str, Any]:
        """Register our webhook (run once per deploy URL, by app.scripts.set_telegram_webhook)."""
        response = await self._http.post(
            f"{self._base}/setWebhook",
            json={
                "url": url,
                "secret_token": secret,
                "allowed_updates": ["message"],  # we only handle /start messages
                "drop_pending_updates": True,
            },
            timeout=TIMEOUT,
        )
        result: dict[str, Any] = response.json()
        return result


def _retry_after(response: httpx.Response) -> float | None:
    try:
        value = response.json().get("parameters", {}).get("retry_after")
    except ValueError:
        return None
    return float(value) if isinstance(value, int | float) else None
