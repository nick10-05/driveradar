"""Fill a *local* database with realistic demo data, for screenshots and the demo video.

    DEMO_PASSWORD=... uv run python -m app.scripts.seed_demo

Creates 3 accounts (an admin and two students), 8 drives in every state (open, urgent,
not eligible, draft, closed, expired) and a tracker with timelines. Uses backend/.env
like the app. All demo accounts get DEMO_PASSWORD (min 12 characters, never printed).

Safe to run again: it first deletes its own accounts and the drives they created, then
recreates everything with deadlines relative to now (so "closes in 18 hours" stays true).

It refuses to run unless ENVIRONMENT=dev and DATABASE_URL points at this machine:
demo drives must never reach the real batch's production database.
"""

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, load_config
from app.core.db import create_engine
from app.core.security import hash_password
from app.models import (
    Application,
    ApplicationEvent,
    Drive,
    DriveAllowedBranch,
    DriveEligibility,
    StudentProfile,
    User,
)
from app.schemas.drive import IST

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "db"}  # "db" = the docker compose service

ADMIN = "demo.admin@example.com"
ASHA = "asha.demo@example.com"  # CSE, 8.1, no backlogs: eligible for most drives
RAVI = "ravi.demo@example.com"  # ECE, 6.9, one backlog: sees the "not eligible" reasons
DEMO_EMAILS = (ADMIN, ASHA, RAVI)


class UnsafeTargetError(Exception):
    pass


def check_target(settings: Settings) -> None:
    """Raise unless this is a dev environment with a local database."""
    if settings.environment != "dev":
        raise UnsafeTargetError(f"ENVIRONMENT must be dev (is {settings.environment})")
    host = make_url(settings.database_url.get_secret_value()).host or ""
    if host not in LOCAL_HOSTS:
        raise UnsafeTargetError("DATABASE_URL must point at a local database")


def _ist(days: int, hour: int, minute: int = 0, *, now: datetime) -> datetime:
    """A deadline `days` from today at hh:mm IST, as UTC (how deadlines are stored)."""
    day = now.astimezone(IST).date() + timedelta(days=days)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST).astimezone(UTC)


def _drive(
    admin: User,
    *,
    company: str,
    role: str,
    deadline: datetime,
    raw_text: str,
    status: str = "published",
    ctc_text: str | None = None,
    ctc_lpa: str | None = None,
    location: str | None = None,
    source: str = "email",
    min_cgpa: str | None = None,
    max_backlogs: int | None = None,
    years: list[int] | None = None,
    branches: tuple[str, ...] = (),
    closed_at: datetime | None = None,
) -> Drive:
    drive = Drive(
        company=company,
        role_title=role,
        ctc_text=ctc_text,
        ctc_lpa=Decimal(ctc_lpa) if ctc_lpa else None,
        location=location,
        apply_link=f"https://careers.example.com/{company.lower().split()[0]}",
        deadline=deadline,
        source=source,
        raw_text=raw_text,
        status=status,
        closed_at=closed_at,
        created_by=admin.id,
    )
    drive.eligibility = DriveEligibility(
        min_cgpa=Decimal(min_cgpa) if min_cgpa else None,
        max_active_backlogs=max_backlogs,
        grad_years=years,
    )
    drive.allowed_branches = [DriveAllowedBranch(branch_code=code) for code in branches]
    return drive


def _track(student: User, drive: Drive, moves: list[str], start: datetime) -> Application:
    """An application that went through `moves`, one event per move, a day or two apart."""
    application = Application(student_id=student.id, drive_id=drive.id, status=moves[-1])
    previous = None
    for step, status in enumerate(moves):
        application.events.append(
            ApplicationEvent(
                from_status=previous, to_status=status, at=start + timedelta(days=2 * step)
            )
        )
        previous = status
    return application


async def remove_demo_data(session: AsyncSession) -> None:
    admin_id = await session.scalar(select(User.id).where(User.email == ADMIN))
    if admin_id is not None:
        # drives.created_by is ON DELETE SET NULL, so delete the demo drives explicitly.
        await session.execute(delete(Drive).where(Drive.created_by == admin_id))
    # Profiles, sessions, applications and notifications cascade with the user.
    await session.execute(delete(User).where(User.email.in_(DEMO_EMAILS)))


async def seed(session: AsyncSession, password: str, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    await remove_demo_data(session)

    password_hash = await hash_password(password)
    admin = User(
        email=ADMIN, name="Placement Cell (demo)", role="admin", password_hash=password_hash
    )
    asha = User(email=ASHA, name="Asha Rao", role="student", password_hash=password_hash)
    ravi = User(email=RAVI, name="Ravi Kumar", role="student", password_hash=password_hash)
    session.add_all([admin, asha, ravi])
    await session.flush()
    session.add_all(
        [
            StudentProfile(
                user_id=asha.id,
                branch_code="CSE",
                cgpa=Decimal("8.10"),
                active_backlogs=0,
                grad_year=2027,
            ),
            StudentProfile(
                user_id=ravi.id,
                branch_code="ECE",
                cgpa=Decimal("6.90"),
                active_backlogs=1,
                grad_year=2027,
            ),
        ]
    )

    zoho = _drive(
        admin,
        company="Zoho Corporation",
        role="Member Technical Staff",
        deadline=_ist(2, 17, now=now),
        ctc_text="7.2 LPA",
        ctc_lpa="7.2",
        location="Chennai",
        min_cgpa="7.0",
        max_backlogs=0,
        years=[2027],
        branches=("CSE", "IT", "ECE"),
        raw_text=(
            "Dear students, Zoho Corporation is hiring Member Technical Staff for the 2027 "
            "batch. Eligible branches: CSE, IT, ECE. CGPA 7.0 and above, no active backlogs. "
            "CTC 7.2 LPA, location Chennai. Register before the deadline. - Placement Cell"
        ),
    )
    razorpay = _drive(
        admin,
        company="Razorpay",
        role="SDE Intern (6 months)",
        deadline=now + timedelta(hours=18),
        ctc_text="Stipend ₹50,000/month, PPO possible",
        location="Bengaluru",
        source="whatsapp",
        min_cgpa="8.0",
        branches=("CSE", "IT"),
        raw_text=(
            "*Razorpay SDE Intern* 🚀 6 months, Bengaluru. Stipend 50k/month, PPO possible. "
            "CSE/IT only, CGPA 8+. Apply by tomorrow!!"
        ),
    )
    infosys = _drive(
        admin,
        company="Infosys",
        role="Systems Engineer",
        deadline=_ist(5, 23, 59, now=now),
        ctc_text="3.6 LPA",
        ctc_lpa="3.6",
        location="Pan India",
        source="portal",
        min_cgpa="6.0",
        max_backlogs=1,
        years=[2027],
        raw_text=(
            "Infosys Systems Engineer drive for the 2027 batch, all branches. Minimum 60% / "
            "6.0 CGPA, at most one active backlog. Package 3.6 LPA."
        ),
    )
    deloitte = _drive(
        admin,
        company="Deloitte USI",
        role="Analyst - Technology Consulting",
        deadline=_ist(12, 18, now=now),
        ctc_text="7.6 LPA",
        ctc_lpa="7.6",
        location="Hyderabad",
        min_cgpa="7.5",
        max_backlogs=0,
        years=[2027],
        raw_text=(
            "Deloitte USI is hiring Analysts (Technology Consulting) from the 2027 batch. "
            "CGPA 7.5+, no backlogs, any branch. 7.6 LPA, Hyderabad."
        ),
    )
    lnt = _drive(
        admin,
        company="L&T Construction",
        role="Graduate Engineer Trainee",
        deadline=_ist(9, 17, now=now),
        ctc_text="4.5 LPA",
        ctc_lpa="4.5",
        location="Mumbai",
        source="portal",
        branches=("CE", "ME", "EEE"),
        raw_text=(
            "L&T Construction GET recruitment: Civil, Mechanical and Electrical branches only. "
            "4.5 LPA, Mumbai."
        ),
    )
    freshworks = _drive(
        admin,
        company="Freshworks",
        role="Software Engineer I",
        deadline=_ist(14, 17, now=now),
        status="draft",
        ctc_text="12 LPA",
        ctc_lpa="12",
        location="Chennai",
        min_cgpa="7.5",
        branches=("CSE", "IT"),
        raw_text=(
            "Freshworks Software Engineer I, 12 LPA, Chennai. CSE and IT, CGPA 7.5 and above. "
            "Last date to apply: two weeks from today."
        ),
    )
    tcs = _drive(
        admin,
        company="TCS Digital",
        role="Digital Engineer",
        deadline=now - timedelta(days=20),
        status="closed",
        closed_at=now - timedelta(days=6),
        ctc_text="7 LPA",
        ctc_lpa="7",
        source="portal",
        min_cgpa="6.0",
        raw_text="TCS Digital hiring for Digital Engineer, 7 LPA, all branches, CGPA 6+.",
    )
    wipro = _drive(
        admin,
        company="Wipro",
        role="Project Engineer",
        deadline=now - timedelta(days=3),
        ctc_text="3.5 LPA",
        ctc_lpa="3.5",
        min_cgpa="6.0",
        raw_text="Wipro Elite NTH: Project Engineer, 3.5 LPA, all branches, CGPA 6.0+.",
    )
    drives = [zoho, razorpay, infosys, deloitte, lnt, freshworks, tcs, wipro]
    session.add_all(drives)
    await session.flush()

    session.add_all(
        [
            _track(asha, tcs, ["applied", "test", "interview", "offer"], now - timedelta(days=28)),
            _track(asha, wipro, ["applied", "rejected"], now - timedelta(days=9)),
            _track(asha, infosys, ["applied", "test"], now - timedelta(days=3)),
            _track(asha, zoho, ["interested"], now - timedelta(days=1)),
            _track(ravi, infosys, ["interested"], now - timedelta(days=1)),
        ]
    )
    await session.commit()
    return {"users": 3, "drives": len(drives), "applications": 5}


async def _main() -> int:  # pragma: no cover - thin CLI wrapper
    settings = load_config()
    try:
        check_target(settings)
    except UnsafeTargetError as exc:
        print(f"Refusing to seed: {exc}")
        return 1
    password = os.environ.get("DEMO_PASSWORD", "")
    if len(password) < 12:
        print("Set DEMO_PASSWORD (at least 12 characters) for the demo accounts.")
        return 1
    engine = create_engine(settings)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            counts = await seed(session, password)
    finally:
        await engine.dispose()
    print(f"Demo data ready: {counts}. Log in as {ADMIN}, {ASHA} or {RAVI} (DEMO_PASSWORD).")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    sys.exit(asyncio.run(_main()))
