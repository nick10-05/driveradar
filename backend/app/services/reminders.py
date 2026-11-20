"""Deadline reminders: 24 h and 3 h before a drive closes (DESIGN §5 F5).

Called by POST /internal/run-reminders, which a GitHub Actions cron hits every 30 min.

Interview notes:
- Time *windows*, not exact times: free cron runs late (often 5-20 min, sometimes more)
  and a sleeping Render instance takes ~30 s to wake. So a run asks "which open drives
  close within the next 24 h (or 3 h)?", never "which close at exactly now + 24 h?".
  Any run inside the window does the job; the first one to get there wins.
- Exactly once: send_once() inserts the notifications row (UNIQUE student/drive/kind)
  before sending. A second run, a retried run or two overlapping runs find the row and
  skip. "Running cron twice sends one message" is the Day 9 test.
- When a drive is already inside 3 h, only the 3 h reminder goes out (never 24 h + 3 h
  back to back, e.g. for a drive published 2 h before its deadline).
- Skips students who already moved past "interested" (applied, test, interview, offer,
  rejected, withdrawn): the reminder is "don't forget to apply". DESIGN names APPLIED and
  WITHDRAWN; the later statuses all imply the student applied.
- Same eligibility check as the feed (D9). Only open drives (published, deadline ahead).
- Runs inside the request (no background task): the cron waits and logs the counts, so a
  failure is visible in the Actions run.
"""

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from pydantic import HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, Drive
from app.services.alerts import (
    PAUSE_BETWEEN_SENDS,
    AlertSummary,
    drive_text,
    linked_profiles,
    send_once,
)
from app.services.drives import facts_of, rules_of, with_rules
from app.services.eligibility import check_eligibility
from app.services.telegram import TelegramClient

log = structlog.get_logger(__name__)

WINDOW_24H = timedelta(hours=24)
WINDOW_3H = timedelta(hours=3)
# Anyone who already applied (or is past applying) doesn't need "don't forget to apply".
REMIND_ONLY = frozenset({"interested"})


@dataclass
class ReminderSummary:
    drives: int = 0
    deadline_24h: AlertSummary = field(default_factory=AlertSummary)
    deadline_3h: AlertSummary = field(default_factory=AlertSummary)


def reminder_kind(deadline: datetime, now: datetime) -> str | None:
    """Which reminder is due for a drive right now (the most urgent one), or None."""
    left = deadline - now
    if left <= timedelta(0):
        return None
    if left <= WINDOW_3H:
        return "deadline_3h"
    if left <= WINDOW_24H:
        return "deadline_24h"
    return None


def reminder_heading(deadline: datetime, now: datetime) -> str:
    hours = max(1, math.ceil((deadline - now) / timedelta(hours=1)))
    unit = "hour" if hours == 1 else "hours"
    return f"Reminder: closes in under {hours} {unit}. Haven't applied yet?"


async def due_drives(session: AsyncSession, now: datetime) -> list[Drive]:
    """Open drives closing within 24 h (uses the (status, deadline) index)."""
    statement = with_rules().where(
        Drive.status == "published", Drive.deadline > now, Drive.deadline <= now + WINDOW_24H
    )
    return list((await session.scalars(statement)).all())


async def run_reminders(
    session: AsyncSession,
    telegram: TelegramClient,
    app_base_url: HttpUrl | None,
    *,
    now: datetime | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> ReminderSummary:
    now = now or datetime.now(UTC)
    summary = ReminderSummary()
    drives = await due_drives(session, now)
    summary.drives = len(drives)
    if not drives:
        return summary

    profiles = await linked_profiles(session)
    drive_ids = [drive.id for drive in drives]
    statuses = {
        (row.student_id, row.drive_id): row.status
        for row in await session.execute(
            select(Application.student_id, Application.drive_id, Application.status).where(
                Application.drive_id.in_(drive_ids)
            )
        )
    }
    # Plain values only from here on: send_once commits, which may expire ORM objects.
    jobs = []
    for drive in drives:
        kind = reminder_kind(drive.deadline, now)
        if kind is None:  # pragma: no cover - due_drives only returns drives in the window
            continue
        rules = rules_of(drive)
        text = drive_text(reminder_heading(drive.deadline, now), drive, app_base_url)
        for profile in profiles:
            status = statuses.get((profile.user_id, drive.id))
            if status is not None and status not in REMIND_ONLY:
                continue
            if profile.telegram_chat_id is None:  # pragma: no cover - filtered in the query
                continue
            if not check_eligibility(facts_of(profile), rules).eligible:
                continue
            jobs.append((profile.user_id, profile.telegram_chat_id, drive.id, kind, text))

    for student_id, chat_id, drive_id, kind, text in jobs:
        result = await send_once(
            session,
            telegram,
            student_id=student_id,
            chat_id=chat_id,
            drive_id=drive_id,
            kind=kind,
            text=text,
        )
        getattr(summary, kind).count(result)
        if result is not None:
            await sleep(PAUSE_BETWEEN_SENDS)

    log.info(
        "reminders_done",
        drives=summary.drives,
        deadline_24h=vars(summary.deadline_24h),
        deadline_3h=vars(summary.deadline_3h),
    )
    return summary
