"""Student side: the feed and a drive's page (DESIGN §5 F3, §8).

Interview notes:
- The feed is locked (409) until the student saves a profile: eligibility depends on it,
  and guessing would show wrong results.
- Ineligible drives are returned too, with reasons. The frontend greys them out; nothing
  is hidden silently.
- Drafts are invisible to students (404, the same as a drive that doesn't exist).
  Closed and expired drives stay reachable by id, for the tracker history (Day 5).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.api.drive_views import student_detail_view, student_view
from app.models import StudentProfile, User
from app.schemas.drive import StudentDriveDetailOut, StudentDriveOut
from app.services.drives import DriveNotFoundError, facts_of, feed, get_drive, rules_of
from app.services.eligibility import check_eligibility
from app.services.profiles import get_profile

router = APIRouter(prefix="/drives", tags=["drives"])

RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Not logged in"},
    status.HTTP_409_CONFLICT: {"description": "Profile not filled in yet"},
}


async def _require_profile(session: DbSession, user: User) -> StudentProfile:
    profile = await get_profile(session, user.id)
    if profile is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Complete your profile to see drives")
    return profile


@router.get("", responses=RESPONSES)
async def list_drives(user: CurrentUser, session: DbSession) -> list[StudentDriveOut]:
    """Open drives with this student's eligibility: eligible first, then by deadline."""
    profile = await _require_profile(session, user)
    now = datetime.now(UTC)
    return [student_view(drive, result, now) for drive, result in await feed(session, profile)]


@router.get(
    "/{drive_id}",
    responses={**RESPONSES, status.HTTP_404_NOT_FOUND: {"description": "No such drive"}},
)
async def get_one_drive(
    drive_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> StudentDriveDetailOut:
    profile = await _require_profile(session, user)
    try:
        drive = await get_drive(session, drive_id, include_drafts=False)
    except DriveNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drive not found") from None
    result = check_eligibility(facts_of(profile), rules_of(drive))
    return student_detail_view(drive, result, datetime.now(UTC))
