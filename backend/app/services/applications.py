"""Application tracker: start tracking a drive, move its status, read the timeline.

DESIGN §5 F4.

Interview notes:
- One PUT does "create or move": the student says where they are now, the server checks
  the state machine and records the move. Illegal → IllegalMoveError (HTTP 409).
- Concurrency: the current row is read with SELECT ... FOR UPDATE, so two quick requests
  for the same tracker run one after the other. Without the lock both could read
  "applied", both move to "test", and the timeline would show the move twice.
- Creating races are handled by the UNIQUE(student, drive) constraint: INSERT ... ON
  CONFLICT DO NOTHING; if another request won, we lock its row and treat this request as
  a move instead of failing with a duplicate-key error.
- Same status again = no move: only the notes change, and no event is written.
- Students can track any drive they can see (published or closed), not drafts.
"""

import uuid
from collections.abc import Sequence

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Application, ApplicationEvent, Drive
from app.services.state_machine import INITIAL, can_move, can_start

log = structlog.get_logger(__name__)


class TrackerDriveNotFoundError(Exception):
    pass


class IllegalMoveError(Exception):
    """A status change the state machine doesn't allow (HTTP 409)."""


async def _locked(
    session: AsyncSession, student_id: uuid.UUID, drive_id: uuid.UUID
) -> Application | None:
    statement = (
        select(Application)
        .where(Application.student_id == student_id, Application.drive_id == drive_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return await session.scalar(statement)


async def set_status(
    session: AsyncSession,
    student_id: uuid.UUID,
    drive_id: uuid.UUID,
    status: str,
    notes: str | None = None,
    *,
    update_notes: bool = False,
) -> Application:
    """Create the tracker or move it to `status`. Notes change only if update_notes."""
    drive_status = await session.scalar(select(Drive.status).where(Drive.id == drive_id))
    if drive_status is None or drive_status == "draft":
        raise TrackerDriveNotFoundError

    application = await _locked(session, student_id, drive_id)
    if application is None:
        if not can_start(status):
            starts = " or ".join(sorted(INITIAL))
            raise IllegalMoveError(f"Start tracking with {starts}")
        values = {"student_id": student_id, "drive_id": drive_id, "status": status}
        if update_notes:
            values["notes"] = notes
        created_id = await session.scalar(
            insert(Application)
            .values(id=uuid.uuid4(), **values)
            .on_conflict_do_nothing(index_elements=["student_id", "drive_id"])
            .returning(Application.id)
        )
        if created_id is not None:
            session.add(ApplicationEvent(application_id=created_id, to_status=status))
            await session.commit()
            log.info("application_started", drive_id=str(drive_id), status=status)
            return await get_application(session, created_id)
        # Another request created it a moment ago: continue as a move on its row.
        application = await _locked(session, student_id, drive_id)
        assert application is not None  # noqa: S101 - the conflicting row exists

    if status != application.status:
        if not can_move(application.status, status):
            raise IllegalMoveError(f"Can't move from {application.status} to {status}")
        session.add(
            ApplicationEvent(
                application_id=application.id, from_status=application.status, to_status=status
            )
        )
        log.info("application_moved", drive_id=str(drive_id), status=status)
        application.status = status
    if update_notes:
        application.notes = notes
    await session.commit()
    return await get_application(session, application.id)


async def get_application(session: AsyncSession, application_id: uuid.UUID) -> Application:
    statement = (
        select(Application)
        .where(Application.id == application_id)
        .options(selectinload(Application.events))
        .execution_options(populate_existing=True)
    )
    application = await session.scalar(statement)
    assert application is not None  # noqa: S101 - callers pass an id that exists
    return application


async def list_applications(
    session: AsyncSession, student_id: uuid.UUID
) -> Sequence[tuple[Application, Drive]]:
    """This student's trackers with their drives, most recently updated first."""
    statement = (
        select(Application, Drive)
        .join(Drive, Drive.id == Application.drive_id)
        .where(Application.student_id == student_id)
        .options(selectinload(Application.events))
        .order_by(Application.updated_at.desc())
    )
    return [(application, drive) for application, drive in await session.execute(statement)]
