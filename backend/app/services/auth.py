"""Registration, login and sessions (DESIGN §5 F1, §7.3).

Interview notes (registration):
- The invite code is checked FIRST. A duplicate email has to return 409 (the user needs
  to know), which tells the caller "this email has an account". Checking the invite code
  before anything else means only batch members can ever learn that.
- No "SELECT first, then INSERT" for the duplicate check: two simultaneous requests could
  both pass the SELECT. The UNIQUE constraint decides atomically; we catch its error.
- Every new account is a student. Admins are promoted by hand in the DB: there is no API
  path to become admin.

Interview notes (sessions):
- Opaque tokens in the DB, not JWTs: logout really ends the session (the row is gone),
  and the cost is one indexed lookup per request.
- Expiry is fixed at login (no sliding window): simple to reason about, and a stolen
  cookie stops working after SESSION_TTL_HOURS at the latest.
- Times are UTC. The expiry check runs in SQL (`expires_at > now()`), so expired sessions
  are filtered out by the same query that finds the user.
- Login always issues a NEW token (never reuses one sent by the browser). That blocks
  session fixation, where an attacker plants a known session ID before the victim logs in.
"""

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import (
    burn_password_check_time,
    hash_password,
    hash_session_token,
    new_session_token,
    secrets_match,
    verify_password,
)
from app.models import User, UserSession
from app.schemas.auth import RegisterIn

log = structlog.get_logger(__name__)


class InvalidInviteCodeError(Exception):
    pass


class EmailAlreadyRegisteredError(Exception):
    pass


async def register_user(session: AsyncSession, data: RegisterIn, settings: Settings) -> User:
    if not secrets_match(
        data.invite_code.get_secret_value(), settings.batch_invite_code.get_secret_value()
    ):
        log.warning("registration_rejected", reason="invalid_invite_code")
        raise InvalidInviteCodeError

    user = User(
        email=data.normalized_email(),
        password_hash=await hash_password(data.password.get_secret_value()),
        name=data.name,
        role="student",
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if "uq_users_email" in str(exc.orig):
            log.info("registration_rejected", reason="email_taken")
            raise EmailAlreadyRegisteredError from exc
        raise

    log.info("user_registered", user_id=str(user.id))  # no email in logs: personal data
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    """The user if email + password match, else None. Same timing either way."""
    user = await session.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        await burn_password_check_time(password)
        return None
    if not await verify_password(password, user.password_hash):
        return None
    return user


async def start_session(session: AsyncSession, user: User, settings: Settings) -> str:
    """Store a new session and return its token (the only time the raw token exists)."""
    token = new_session_token()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours),
        )
    )
    await session.commit()
    log.info("session_started", user_id=str(user.id))
    return token


async def user_for_token(session: AsyncSession, token: str) -> User | None:
    """The user behind a cookie token, if the session exists and hasn't expired."""
    return await session.scalar(
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(
            UserSession.token_hash == hash_session_token(token),
            UserSession.expires_at > func.now(),
        )
    )


async def end_session(session: AsyncSession, token: str) -> None:
    """Delete the session for this token. Unknown or expired tokens are a no-op."""
    await session.execute(
        delete(UserSession).where(UserSession.token_hash == hash_session_token(token))
    )
    await session.commit()
