"""Student profiles.

Interview notes:
- Saving is an UPSERT (INSERT ... ON CONFLICT (user_id) DO UPDATE): one atomic statement
  for "create or replace". Two quick saves from two tabs can't race into a duplicate-key
  error, which "SELECT, then INSERT or UPDATE" could.
- Only the four profile fields are written. The Telegram columns are owned by the Day 8
  link flow and are never touched here.
"""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Branch, StudentProfile
from app.schemas.profile import ProfileIn

log = structlog.get_logger(__name__)


class UnknownBranchError(Exception):
    pass


async def get_profile(session: AsyncSession, user_id: uuid.UUID) -> StudentProfile | None:
    return await session.get(StudentProfile, user_id)


async def save_profile(
    session: AsyncSession, user_id: uuid.UUID, data: ProfileIn
) -> StudentProfile:
    if await session.get(Branch, data.branch_code) is None:
        raise UnknownBranchError

    values = data.model_dump()
    statement = (
        insert(StudentProfile)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(index_elements=[StudentProfile.user_id], set_=values)
        .returning(StudentProfile)
    )
    # populate_existing: refresh any copy already in the session with the new values.
    profile: StudentProfile | None = await session.scalar(
        select(StudentProfile).from_statement(statement).execution_options(populate_existing=True)
    )
    await session.commit()
    assert profile is not None  # noqa: S101 - RETURNING always yields the row
    log.info("profile_saved", user_id=str(user_id))
    return profile
