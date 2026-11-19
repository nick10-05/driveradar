"""Drives: admin create / edit / publish / close, and the student feed (DESIGN §5 F2/F3).

Interview notes:
- Stored status moves one way only: draft → published → closed. Any other change raises
  DriveStateError (HTTP 409). A closed drive is final and read-only.
- Publishing needs a future deadline: publishing an already-expired drive would never
  reach the feed, and is almost always a typo in the date.
- "Expired" is computed (drive_state), never stored. The feed query filters on
  `deadline > now()` in SQL, using the (status, deadline) index.
- Branch codes in rules are checked against `branches` here, so the admin gets
  "Unknown branch codes: XYZ" instead of a foreign-key error.
- Relationships are lazy="raise": every query states what it loads (selectinload), so
  an accidental lazy load (which async SQLAlchemy can't do) fails loudly in tests.
- Eligibility itself is the pure check_eligibility(); this module only converts DB rows
  into its inputs and sorts the result (eligible first, then soonest deadline).
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Branch, Drive, DriveAllowedBranch, DriveEligibility, StudentProfile
from app.schemas.drive import DriveCreate, DriveState, DriveUpdate, EligibilityRulesIn
from app.services.eligibility import (
    EligibilityResult,
    EligibilityRules,
    StudentFacts,
    check_eligibility,
)

log = structlog.get_logger(__name__)


# (from, to) pairs. Same-status pairs allow plain edits; closed has no way out.
_ALLOWED_STATUS_CHANGES = frozenset(
    {
        ("draft", "draft"),
        ("draft", "published"),
        ("published", "published"),
        ("published", "closed"),
    }
)


class DriveNotFoundError(Exception):
    pass


class DriveStateError(Exception):
    """An illegal status change or an edit to a closed drive (HTTP 409)."""


class PastDeadlineError(Exception):
    pass


class UnknownBranchesError(Exception):
    def __init__(self, codes: Sequence[str]) -> None:
        super().__init__(", ".join(codes))
        self.codes = list(codes)


# ---------------------------------------------------------------- pure helpers


def drive_state(drive: Drive, now: datetime) -> DriveState:
    if drive.status == "draft":
        return "draft"
    if drive.status == "closed":
        return "closed"
    return "open" if drive.deadline > now else "expired"


def rules_of(drive: Drive) -> EligibilityRules:
    rules = drive.eligibility
    return EligibilityRules(
        min_cgpa=rules.min_cgpa,
        max_active_backlogs=rules.max_active_backlogs,
        grad_years=frozenset(rules.grad_years or ()),
        allowed_branches=frozenset(branch.branch_code for branch in drive.allowed_branches),
    )


def facts_of(profile: StudentProfile) -> StudentFacts:
    return StudentFacts(
        branch_code=profile.branch_code,
        cgpa=profile.cgpa,
        active_backlogs=profile.active_backlogs,
        grad_year=profile.grad_year,
    )


# ---------------------------------------------------------------- queries


def _with_rules() -> Select[Drive]:
    return select(Drive).options(
        selectinload(Drive.eligibility), selectinload(Drive.allowed_branches)
    )


async def get_drive(session: AsyncSession, drive_id: uuid.UUID, *, include_drafts: bool) -> Drive:
    statement = _with_rules().where(Drive.id == drive_id)
    if not include_drafts:
        statement = statement.where(Drive.status != "draft")
    drive = await session.scalar(statement.execution_options(populate_existing=True))
    if drive is None:
        raise DriveNotFoundError
    return drive


async def list_all_drives(session: AsyncSession) -> Sequence[Drive]:
    """Admin list: every drive, newest first."""
    return (await session.scalars(_with_rules().order_by(Drive.created_at.desc()))).all()


async def feed(
    session: AsyncSession, profile: StudentProfile
) -> list[tuple[Drive, EligibilityResult]]:
    """Open drives (published, deadline in the future): eligible first, then by deadline."""
    statement = _with_rules().where(Drive.status == "published", Drive.deadline > func.now())
    drives = (await session.scalars(statement)).all()
    student = facts_of(profile)
    results = [(drive, check_eligibility(student, rules_of(drive))) for drive in drives]
    results.sort(key=lambda item: (not item[1].eligible, item[0].deadline))
    return results


# ---------------------------------------------------------------- writes


async def _check_branches(session: AsyncSession, codes: list[str]) -> None:
    if not codes:
        return
    known = set(await session.scalars(select(Branch.code).where(Branch.code.in_(codes))))
    unknown = [code for code in codes if code not in known]
    if unknown:
        raise UnknownBranchesError(unknown)


def _set_rules(drive: Drive, rules: EligibilityRulesIn) -> None:
    drive.eligibility = DriveEligibility(
        min_cgpa=rules.min_cgpa,
        max_active_backlogs=rules.max_active_backlogs,
        grad_years=rules.grad_years or None,  # empty = any year, stored as NULL
    )
    drive.allowed_branches = [
        DriveAllowedBranch(branch_code=code) for code in rules.allowed_branches
    ]


def _column_values(data: DriveCreate | DriveUpdate, *, only_sent: bool) -> dict[str, Any]:
    values = data.model_dump(exclude={"eligibility", "status"}, exclude_unset=only_sent)
    if values.get("apply_link") is not None:
        values["apply_link"] = str(values["apply_link"])
    return values


async def create_drive(session: AsyncSession, data: DriveCreate, created_by: uuid.UUID) -> Drive:
    """Always creates a draft. Publishing is a separate, deliberate step."""
    await _check_branches(session, data.eligibility.allowed_branches)
    drive = Drive(**_column_values(data, only_sent=False), created_by=created_by, status="draft")
    _set_rules(drive, data.eligibility)
    session.add(drive)
    await session.commit()
    log.info("drive_created", drive_id=str(drive.id))
    return await get_drive(session, drive.id, include_drafts=True)


async def update_drive(session: AsyncSession, drive_id: uuid.UUID, data: DriveUpdate) -> Drive:
    drive = await get_drive(session, drive_id, include_drafts=True)
    now = datetime.now(UTC)

    # Validate everything first, then change the object: a rejected request must not
    # leave half-applied changes in the session.
    if drive.status == "closed":
        raise DriveStateError("A closed drive can't be changed")
    new_status = data.status or drive.status
    if (drive.status, new_status) not in _ALLOWED_STATUS_CHANGES:
        raise DriveStateError(f"Can't change a {drive.status} drive to {new_status}")
    deadline = data.deadline or drive.deadline
    if drive.status == "draft" and new_status == "published" and deadline <= now:
        raise PastDeadlineError
    if data.eligibility is not None:
        await _check_branches(session, data.eligibility.allowed_branches)

    if data.eligibility is not None:
        _set_rules(drive, data.eligibility)
    for name, value in _column_values(data, only_sent=True).items():
        setattr(drive, name, value)
    if new_status != drive.status:
        drive.status = new_status
        if new_status == "closed":
            drive.closed_at = now

    await session.commit()
    log.info("drive_updated", drive_id=str(drive.id), status=drive.status)
    return await get_drive(session, drive.id, include_drafts=True)
