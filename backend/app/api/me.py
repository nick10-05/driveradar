"""The logged-in user's own data: GET /me, PUT /me/profile."""

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.models import User
from app.schemas.profile import MeOut, ProfileIn, ProfileOut
from app.services.profiles import UnknownBranchError, get_profile, save_profile

router = APIRouter(prefix="/me", tags=["me"])

NOT_LOGGED_IN: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Not logged in"}
}


def me_out(user: User, profile: ProfileOut | None) -> MeOut:
    return MeOut(id=user.id, email=user.email, name=user.name, role=user.role, profile=profile)


@router.get("", responses=NOT_LOGGED_IN)
async def get_me(user: CurrentUser, session: DbSession) -> MeOut:
    profile = await get_profile(session, user.id)
    return me_out(user, ProfileOut.from_model(profile) if profile else None)


@router.put(
    "/profile",
    responses={
        **NOT_LOGGED_IN,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Invalid values or unknown branch"},
    },
)
async def put_profile(data: ProfileIn, user: CurrentUser, session: DbSession) -> ProfileOut:
    """Create or replace the profile. PUT because the whole profile is sent each time."""
    try:
        profile = await save_profile(session, user.id, data)
    except UnknownBranchError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown branch code") from None
    return ProfileOut.from_model(profile)
