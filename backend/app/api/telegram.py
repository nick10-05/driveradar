"""POST /telegram/webhook: Telegram calls this with bot updates (DESIGN §5 F5, §7.3).

Interview notes:
- Security: Telegram sends back the secret we gave it in setWebhook, in the header
  X-Telegram-Bot-Api-Secret-Token. We compare it in constant time; anything else gets 401
  before the body is even looked at. The URL is public, so this is the only thing stopping
  someone from faking "/start <token>" messages.
- No cookie and no Origin header (it's a server, not a browser), so the Origin check is
  skipped for this path (core/origin.py) and the secret header replaces it.
- We answer 200 for every authentic update, even ones we ignore: Telegram retries
  non-2xx responses, and a retry loop on a message we'll never handle helps nobody.
- Replies go in the response body ({"method": "sendMessage", ...}), a Bot API feature for
  webhooks. No extra outbound request, and the bot token isn't needed on this path.
- Only private chats count: in a group, "chat.id" is the group, and alerts about one
  student's eligibility must not go to a group.
- Not in the OpenAPI schema: it's for Telegram, not for our frontend.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.api.deps import AppSettings, DbSession
from app.core.security import secrets_match
from app.services.telegram_link import complete_link


def verify_webhook_secret(
    settings: AppSettings,
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> None:
    """A router dependency, so it runs before the body is parsed: a caller without the
    secret gets 401 and learns nothing about what a valid body looks like."""
    expected = settings.telegram_webhook_secret
    if expected is None:  # Telegram is off: behave as if the route didn't exist
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    if secret is None or not secrets_match(secret, expected.get_secret_value()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad webhook secret")


router = APIRouter(
    prefix="/telegram", include_in_schema=False, dependencies=[Depends(verify_webhook_secret)]
)

LINKED = "Connected! You'll get DriveRadar alerts here for new drives you're eligible for."
BAD_LINK = (
    "This link has expired or was already used. "
    "Open your DriveRadar profile and tap Connect Telegram again."
)
HELP = "To get alerts, open your DriveRadar profile and tap Connect Telegram."


class _Chat(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    type: str


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chat: _Chat
    text: str | None = None


class Update(BaseModel):
    """Only the fields we use; Telegram sends many more."""

    model_config = ConfigDict(extra="ignore")
    update_id: int
    message: _Message | None = None


def _reply(chat_id: int, text: str) -> dict[str, Any]:
    return {"method": "sendMessage", "chat_id": chat_id, "text": text}


@router.post("/webhook")
async def webhook(update: Update, session: DbSession) -> dict[str, Any]:
    message = update.message
    if message is None or message.chat.type != "private" or not message.text:
        return {}
    command, _, argument = message.text.strip().partition(" ")
    if command.split("@")[0] != "/start":  # "/start@BotName" is the same command
        return {}
    token = argument.strip()
    if not token:
        return _reply(message.chat.id, HELP)
    linked = await complete_link(session, token, message.chat.id)
    return _reply(message.chat.id, LINKED if linked else BAD_LINK)
