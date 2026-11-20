"""Telegram alerts: "a drive you're eligible for was just published" (DESIGN §5 F5).

Deadline reminders (services/reminders.py) reuse send_once(), drive_text() and the
linked-student list from here.

Interview notes:
- Runs as a FastAPI background task after the publish response is sent, so the admin
  doesn't wait for N Telegram calls. It opens its own DB session: the request's session
  is closed by then. Trade-off: if the server dies mid-send, the rest of that batch is
  lost (no queue, by design). A crash can't cause duplicates though, see next point.
- Eligibility is the same pure check_eligibility() the feed uses (D9): the alert list and
  the feed can never disagree.
- Insert-then-send: INSERT ... ON CONFLICT DO NOTHING into notifications, and send only if
  a row came back. The UNIQUE(student, drive, kind) constraint makes a second publish or
  a parallel run a no-op, decided by the database rather than by timing.
- On a temporary failure the row is deleted, so a later run may try again. On 403 (bot
  blocked) the row is deleted and the chat unlinked: we stop messaging people who
  said no.
- ~20 messages a second: Telegram's limit is about 30/s per bot, and 429s are handled
  by the client anyway.
- No student data goes anywhere except their own chat; the message is about the drive.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from pydantic import HttpUrl
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionFactory
from app.models import Drive, Notification, StudentProfile
from app.schemas.drive import IST
from app.services.drives import DriveNotFoundError, facts_of, get_drive, rules_of
from app.services.eligibility import check_eligibility
from app.services.telegram import SendResult, TelegramClient
from app.services.telegram_link import unlink_chat

log = structlog.get_logger(__name__)

PAUSE_BETWEEN_SENDS = 0.05  # seconds: ~20 messages/s


@dataclass
class AlertSummary:
    eligible: int = 0
    sent: int = 0
    skipped: int = 0  # already notified
    failed: int = 0
    blocked: int = 0

    def count(self, result: SendResult | None) -> None:
        if result is None:
            self.skipped += 1
        elif result is SendResult.SENT:
            self.sent += 1
        elif result is SendResult.BLOCKED:
            self.blocked += 1
        else:
            self.failed += 1


def drive_text(heading: str, drive: Drive, app_base_url: HttpUrl | None) -> str:
    """Plain text (no parse_mode), so nothing in a company name can format or inject."""
    deadline = drive.deadline.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")
    lines = [heading, f"{drive.company} - {drive.role_title}"]
    if drive.ctc_text:
        lines.append(f"CTC: {drive.ctc_text}")
    if drive.location:
        lines.append(f"Location: {drive.location}")
    lines.append(f"Apply by: {deadline}")
    if app_base_url is not None:
        lines.append(f"{str(app_base_url).rstrip('/')}/drives/{drive.id}")
    return "\n".join(lines)


def new_drive_text(drive: Drive, app_base_url: HttpUrl | None) -> str:
    return drive_text("New drive you're eligible for", drive, app_base_url)


async def linked_profiles(session: AsyncSession) -> list[StudentProfile]:
    """Every student who connected Telegram (eligibility is checked per drive by the caller)."""
    result = await session.scalars(
        select(StudentProfile).where(StudentProfile.telegram_chat_id.is_not(None))
    )
    return list(result.all())


async def send_once(
    session: AsyncSession,
    telegram: TelegramClient,
    *,
    student_id: uuid.UUID,
    chat_id: int,
    drive_id: uuid.UUID,
    kind: str,
    text: str,
) -> SendResult | None:
    """Send one alert unless it was already sent. Returns None when skipped as a duplicate."""
    inserted = await session.scalar(
        insert(Notification)
        .values(student_id=student_id, drive_id=drive_id, kind=kind)
        .on_conflict_do_nothing(index_elements=["student_id", "drive_id", "kind"])
        .returning(Notification.id)
    )
    await session.commit()  # the claim is visible to every other run before we send
    if inserted is None:
        return None

    result = await telegram.send_message(chat_id, text)
    if result is not SendResult.SENT:
        await session.execute(delete(Notification).where(Notification.id == inserted))
        await session.commit()
        if result is SendResult.BLOCKED:
            await unlink_chat(session, chat_id)
    return result


async def send_new_drive_alerts(
    session_factory: SessionFactory,
    telegram: TelegramClient,
    drive_id: uuid.UUID,
    app_base_url: HttpUrl | None,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AlertSummary:
    summary = AlertSummary()
    async with session_factory() as session:
        try:
            drive = await get_drive(session, drive_id, include_drafts=False)
        except DriveNotFoundError:
            return summary
        if drive.status != "published" or drive.deadline <= datetime.now(UTC):
            return summary  # closed or expired before we got to it

        rules = rules_of(drive)
        text = new_drive_text(drive, app_base_url)
        # (user_id, chat_id) pairs, read up front: send_once commits, which would expire
        # the ORM objects mid-loop.
        recipients = [
            (profile.user_id, profile.telegram_chat_id)
            for profile in await linked_profiles(session)
            if profile.telegram_chat_id is not None
            and check_eligibility(facts_of(profile), rules).eligible
        ]
        summary.eligible = len(recipients)

        for student_id, chat_id in recipients:
            result = await send_once(
                session,
                telegram,
                student_id=student_id,
                chat_id=chat_id,
                drive_id=drive_id,
                kind="new_drive",
                text=text,
            )
            summary.count(result)
            if result is not None:
                await sleep(PAUSE_BETWEEN_SENDS)

    log.info("new_drive_alerts_done", drive_id=str(drive_id), **vars(summary))
    return summary


async def new_drive_alerts_task(
    session_factory: SessionFactory,
    telegram: TelegramClient,
    drive_id: uuid.UUID,
    app_base_url: HttpUrl | None,
) -> None:
    """The background-task entry point. It runs after the response was sent, so nobody is
    there to see an exception: log one structured event (searchable in Render's logs)
    instead of a bare traceback. Already-sent alerts stay recorded; a re-run can't
    duplicate them."""
    try:
        await send_new_drive_alerts(session_factory, telegram, drive_id, app_base_url)
    except Exception:
        log.exception("new_drive_alerts_failed", drive_id=str(drive_id))
