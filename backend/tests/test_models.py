"""The database itself enforces the data rules (real Postgres).

These rules also get checked in the API layer later. Testing them at the DB level proves
the second line of defence works: bad data can't get in even through a buggy code path.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BranchAlias, StudentProfile, User, UserSession

pytestmark = [pytest.mark.anyio, pytest.mark.db]


def make_user(**overrides: Any) -> User:
    fields: dict[str, Any] = {
        "email": f"student-{uuid.uuid4().hex[:8]}@example.com",
        "password_hash": "not-a-real-hash",
        "name": "Test Student",
    } | overrides
    return User(**fields)


def make_profile(user: User, **overrides: Any) -> StudentProfile:
    fields: dict[str, Any] = {
        "user_id": user.id,
        "branch_code": "CSE",
        "cgpa": Decimal("7.50"),
        "grad_year": 2027,
    } | overrides
    return StudentProfile(**fields)


async def test_new_user_defaults(db_session: AsyncSession) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)

    assert isinstance(user.id, uuid.UUID)
    assert user.role == "student"
    assert user.created_at.tzinfo is not None  # timestamptz, stored in UTC


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"email": "Student@Example.com"}, "ck_users_email_lowercase"),
        ({"role": "superuser"}, "ck_users_role"),
    ],
)
async def test_user_check_constraints(
    db_session: AsyncSession, overrides: dict[str, Any], constraint: str
) -> None:
    db_session.add(make_user(**overrides))

    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


async def test_email_is_unique(db_session: AsyncSession) -> None:
    db_session.add(make_user(email="same@example.com"))
    await db_session.flush()
    db_session.add(make_user(email="same@example.com"))

    with pytest.raises(IntegrityError, match="uq_users_email"):
        await db_session.flush()


async def test_cgpa_keeps_exact_decimals(db_session: AsyncSession) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.flush()
    db_session.add(make_profile(user, cgpa=Decimal("7.5")))
    await db_session.flush()
    db_session.expunge_all()  # force a real read from the DB

    profile = await db_session.get_one(StudentProfile, user.id)

    assert profile.cgpa == Decimal("7.50")
    assert profile.active_backlogs == 0  # server default


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"cgpa": Decimal("10.01")}, "ck_student_profiles_cgpa_range"),
        ({"cgpa": Decimal("-0.01")}, "ck_student_profiles_cgpa_range"),
        ({"active_backlogs": -1}, "ck_student_profiles_active_backlogs_non_negative"),
        ({"branch_code": "NOPE"}, "fk_student_profiles_branch_code_branches"),
    ],
)
async def test_profile_rejects_invalid_values(
    db_session: AsyncSession, overrides: dict[str, Any], constraint: str
) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.flush()
    db_session.add(make_profile(user, **overrides))

    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


async def test_alias_must_point_to_an_existing_branch(db_session: AsyncSession) -> None:
    db_session.add(BranchAlias(alias="unknown branch", branch_code="NOPE"))

    with pytest.raises(IntegrityError, match="fk_branch_aliases_branch_code_branches"):
        await db_session.flush()


async def test_deleting_a_user_deletes_their_sessions_and_profile(
    db_session: AsyncSession,
) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.flush()
    db_session.add_all(
        [
            UserSession(
                user_id=user.id,
                token_hash=uuid.uuid4().hex,
                expires_at=datetime.now(UTC) + timedelta(days=7),
            ),
            make_profile(user),
        ]
    )
    await db_session.flush()

    await db_session.execute(delete(User).where(User.id == user.id))

    sessions = await db_session.scalar(
        select(func.count()).select_from(UserSession).where(UserSession.user_id == user.id)
    )
    profiles = await db_session.scalar(
        select(func.count()).select_from(StudentProfile).where(StudentProfile.user_id == user.id)
    )
    assert (sessions, profiles) == (0, 0)
