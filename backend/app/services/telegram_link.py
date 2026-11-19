"""Linking a student's Telegram chat to their account (DESIGN §5 F5).

Flow: the profile page asks for a link -> we store sha256(token) + expiry and return
t.me/<bot>?start=<token> -> the student taps it, Telegram sends "/start <token>" to our
webhook -> we look up the hash, save the chat_id and clear the token.

Interview notes:
- Why a token at all: the webhook only tells us "chat 12345 said /start". The token proves
  that chat belongs to the logged-in student who asked for the link. Without it anyone
  could claim to be anyone.
- Stored hashed (like session tokens): someone reading the DB can't use a pending link.
  256 random bits, so plain SHA-256 is enough (nothing to brute-force).
- Single-use and 15 minutes: the lookup requires expires_at > now, and the same UPDATE
  that saves chat_id clears the token. One statement, so two quick taps can't both win.
- One Telegram chat belongs to one student (chat_id is UNIQUE). If that chat was linked
  to another account before, that link is removed first, so the newest link wins instead
  of failing on the unique constraint.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_session_token, new_session_token
from app.models import StudentProfile

log = structlog.get_logger(__name__)

LINK_TTL = timedelta(minutes=15)


class NoProfileError(Exception):
    """Alerts depend on eligibility, which needs a profile."""


async def start_link(
    session: AsyncSession, user_id: uuid.UUID, now: datetime | None = None
) -> tuple[str, datetime]:
    """New one-time token for this student (replaces any pending one). Returns (token, expiry)."""
    now = now or datetime.now(UTC)
    token = new_session_token()
    expires_at = now + LINK_TTL
    result = await session.execute(
        update(StudentProfile)
        .where(StudentProfile.user_id == user_id)
        .values(
            telegram_link_token_hash=hash_session_token(token), telegram_link_expires_at=expires_at
        )
        .returning(StudentProfile.user_id)
    )
    if result.scalar_one_or_none() is None:
        raise NoProfileError
    await session.commit()
    log.info("telegram_link_started")
    return token, expires_at


async def complete_link(
    session: AsyncSession, token: str, chat_id: int, now: datetime | None = None
) -> uuid.UUID | None:
    """Called by the webhook on "/start <token>". Returns the linked user's id, or None
    if the token is unknown, already used or expired."""
    now = now or datetime.now(UTC)
    token_hash = hash_session_token(token)
    # Free this chat from any other account first (UNIQUE chat_id; the newest link wins).
    await session.execute(
        update(StudentProfile)
        .where(
            StudentProfile.telegram_chat_id == chat_id,
            StudentProfile.telegram_link_token_hash.is_distinct_from(token_hash),
        )
        .values(telegram_chat_id=None)
    )
    result = await session.execute(
        update(StudentProfile)
        .where(
            StudentProfile.telegram_link_token_hash == token_hash,
            StudentProfile.telegram_link_expires_at > now,
        )
        .values(
            telegram_chat_id=chat_id,
            telegram_link_token_hash=None,
            telegram_link_expires_at=None,
        )
        .returning(StudentProfile.user_id)
    )
    user_id = result.scalar_one_or_none()
    if user_id is None:
        await session.rollback()  # don't unlink the other account for a bad token
        log.info("telegram_link_rejected")
        return None
    await session.commit()
    log.info("telegram_linked", user_id=str(user_id))
    return user_id


async def unlink_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Disconnect from the profile page. Also cancels a pending link."""
    await session.execute(
        update(StudentProfile)
        .where(StudentProfile.user_id == user_id)
        .values(telegram_chat_id=None, telegram_link_token_hash=None, telegram_link_expires_at=None)
    )
    await session.commit()
    log.info("telegram_unlinked", reason="user")


async def unlink_chat(session: AsyncSession, chat_id: int) -> None:
    """The student blocked the bot (Telegram answered 403): stop sending to that chat."""
    await session.execute(
        update(StudentProfile)
        .where(StudentProfile.telegram_chat_id == chat_id)
        .values(telegram_chat_id=None)
    )
    await session.commit()
    log.info("telegram_unlinked", reason="blocked")
