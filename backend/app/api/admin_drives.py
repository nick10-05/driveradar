"""Admin side: create, list, edit, publish and close drives (DESIGN §5 F2, §8).

Interview notes:
- Every route depends on CurrentAdmin: 401 when logged out, 403 for students. The check
  is a dependency on each route (via the router), so a new route can't forget it.
- Create always makes a draft. Publishing is an explicit PATCH {"status": "published"},
  which is the human approval step the AI boundary (D9) relies on from Day 4.
- Errors map to clear statuses: 404 unknown drive, 409 illegal status change or edit to a
  closed drive, 422 bad input (past deadline on publish, unknown branch codes).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentAdmin, DbSession, current_admin
from app.api.drive_views import admin_view
from app.schemas.drive import AdminDriveOut, DriveCreate, DriveUpdate
from app.services.drives import (
    DriveNotFoundError,
    DriveStateError,
    PastDeadlineError,
    UnknownBranchesError,
    create_drive,
    get_drive,
    list_all_drives,
    update_drive,
)

router = APIRouter(
    prefix="/admin/drives",
    tags=["admin"],
    dependencies=[Depends(current_admin)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Not logged in"},
        status.HTTP_403_FORBIDDEN: {"description": "Not an admin"},
    },
)

NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"description": "No such drive"}
}


def _unknown_branches(exc: UnknownBranchesError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown branch codes: {', '.join(exc.codes)}"
    )


@router.get("")
async def list_drives(session: DbSession) -> list[AdminDriveOut]:
    """Every drive, drafts included, newest first."""
    now = datetime.now(UTC)
    return [admin_view(drive, now) for drive in await list_all_drives(session)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(data: DriveCreate, admin: CurrentAdmin, session: DbSession) -> AdminDriveOut:
    try:
        drive = await create_drive(session, data, created_by=admin.id)
    except UnknownBranchesError as exc:
        raise _unknown_branches(exc) from None
    return admin_view(drive, datetime.now(UTC))


@router.get("/{drive_id}", responses=NOT_FOUND)
async def get_one(drive_id: uuid.UUID, session: DbSession) -> AdminDriveOut:
    try:
        drive = await get_drive(session, drive_id, include_drafts=True)
    except DriveNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drive not found") from None
    return admin_view(drive, datetime.now(UTC))


@router.patch(
    "/{drive_id}",
    responses={
        **NOT_FOUND,
        status.HTTP_409_CONFLICT: {"description": "Illegal status change or drive is closed"},
    },
)
async def patch(drive_id: uuid.UUID, data: DriveUpdate, session: DbSession) -> AdminDriveOut:
    """Edit fields, publish ({"status": "published"}) or close ({"status": "closed"})."""
    try:
        drive = await update_drive(session, drive_id, data)
    except DriveNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drive not found") from None
    except DriveStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except PastDeadlineError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Can't publish: the deadline has passed"
        ) from None
    except UnknownBranchesError as exc:
        raise _unknown_branches(exc) from None
    return admin_view(drive, datetime.now(UTC))
