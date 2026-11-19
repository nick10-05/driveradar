"""The logged-in user's own data: GET /me, PUT /me/profile, GET /me/applications,
POST/DELETE /me/telegram-link."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import AppSettings, CurrentUser, DbSession
from app.api.drive_views import tracker_entry_view
from app.models import User
from app.schemas.application import TrackerEntryOut
from app.schemas.profile import MeOut, ProfileIn, ProfileOut, TelegramLinkOut
from app.services.applications import list_applications
from app.services.profiles import UnknownBranchError, get_profile, save_profile
from app.services.telegram_link import NoProfileError, start_link, unlink_user

router = APIRouter(prefix="/me", tags=["me"])

NOT_LOGGED_IN: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Not logged in"}
}


def me_out(user: User, profile: ProfileOut | None, *, telegram_available: bool) -> MeOut:
    return MeOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        profile=profile,
        telegram_available=telegram_available,
    )


@router.get("", responses=NOT_LOGGED_IN)
async def get_me(user: CurrentUser, session: DbSession, settings: AppSettings) -> MeOut:
    profile = await get_profile(session, user.id)
    return me_out(
        user,
        ProfileOut.from_model(profile) if profile else None,
        telegram_available=settings.telegram_enabled,
    )


@router.get("/applications", responses=NOT_LOGGED_IN)
async def get_my_applications(user: CurrentUser, session: DbSession) -> list[TrackerEntryOut]:
    """My tracker: every drive I track, with its current status and timeline."""
    now = datetime.now(UTC)
    rows = await list_applications(session, user.id)
    return [tracker_entry_view(application, drive, now) for application, drive in rows]


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


@router.post(
    "/telegram-link",
    status_code=status.HTTP_201_CREATED,
    responses={
        **NOT_LOGGED_IN,
        status.HTTP_404_NOT_FOUND: {"description": "Telegram isn't set up on this server"},
        status.HTTP_409_CONFLICT: {"description": "Save a profile first"},
    },
)
async def post_telegram_link(
    user: CurrentUser, session: DbSession, settings: AppSettings
) -> TelegramLinkOut:
    """A one-time deep link (15 minutes) that connects this account to a Telegram chat."""
    if settings.telegram_bot_username is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Telegram alerts aren't set up")
    try:
        token, expires_at = await start_link(session, user.id)
    except NoProfileError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Save your profile first") from None
    return TelegramLinkOut(
        url=f"https://t.me/{settings.telegram_bot_username}?start={token}", expires_at=expires_at
    )


@router.delete("/telegram-link", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_LOGGED_IN)
async def delete_telegram_link(user: CurrentUser, session: DbSession) -> Response:
    """Disconnect Telegram (no more alerts). Safe to call when not connected."""
    await unlink_user(session, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
