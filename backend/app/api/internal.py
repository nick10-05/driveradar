"""POST /internal/run-reminders: the cron job (DESIGN §5 F5, §8).

A GitHub Actions schedule calls this every 30 minutes. It sends due deadline reminders
and does housekeeping (expired sessions, expired Telegram link tokens).

Interview notes:
- Why an external cron: Render's free instance sleeps after ~15 min idle, so an
  in-process scheduler (APScheduler, asyncio loop) would simply not run while asleep.
  The cron's HTTP call is what wakes it up.
- Auth: the X-Cron-Secret header must match CRON_SECRET (constant-time compare), checked
  in a router dependency before anything else runs. Not cookie-based, so the Origin
  check skips /internal/ (core/origin.py).
- Safe to call any number of times: reminders are exactly-once via the notifications
  unique constraint, and the cleanups delete only what is already expired. So the cron
  can retry freely while Render is waking up.
- Telegram off = reminders skipped, cleanup still runs.
- Hidden from OpenAPI: it's for the cron, not the frontend.
"""

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.deps import AppSettings, DbSession, Telegram
from app.core.security import secrets_match
from app.services.auth import delete_expired_sessions
from app.services.reminders import run_reminders
from app.services.telegram_link import clear_expired_link_tokens


def verify_cron_secret(
    settings: AppSettings,
    secret: Annotated[str | None, Header(alias="X-Cron-Secret")] = None,
) -> None:
    if secret is None or not secrets_match(secret, settings.cron_secret.get_secret_value()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad cron secret")


router = APIRouter(
    prefix="/internal", include_in_schema=False, dependencies=[Depends(verify_cron_secret)]
)


@router.post("/run-reminders")
async def run_reminders_job(
    session: DbSession, settings: AppSettings, telegram: Telegram
) -> dict[str, Any]:
    reminders = None
    if telegram is not None:
        summary = await run_reminders(session, telegram, settings.app_base_url)
        reminders = asdict(summary)
    return {
        "telegram_enabled": telegram is not None,
        "reminders": reminders,
        "expired_sessions_deleted": await delete_expired_sessions(session),
        "expired_link_tokens_cleared": await clear_expired_link_tokens(session),
    }
