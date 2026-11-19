"""The application tracker over HTTP (real Postgres).

Day 5 "done when" (tracker half): an illegal move returns 409; the timeline is recorded.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.db import create_engine
from app.models import Application, ApplicationEvent, Drive, User
from app.services.applications import set_status
from tests.conftest import api_client
from tests.helpers import create, iso, publish, sign_in, with_database_url

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def put(client: httpx.AsyncClient, drive_id: str, **body: Any) -> httpx.Response:
    return await client.put(f"/drives/{drive_id}/application", json=body)


def moves(body: dict[str, Any]) -> list[tuple[str | None, str]]:
    return [(e["from_status"], e["to_status"]) for e in body["timeline"]]


# ---------------------------------------------------------------- done when


async def test_moves_are_recorded_as_a_timeline(
    admin: httpx.AsyncClient, student: httpx.AsyncClient
) -> None:
    drive = await publish(admin)

    for status in ("interested", "applied", "test", "interview", "offer"):
        response = await put(student, drive["id"], status=status)
        assert response.status_code == 200, response.text

    body = response.json()
    assert body["status"] == "offer"
    assert moves(body) == [
        (None, "interested"),
        ("interested", "applied"),
        ("applied", "test"),
        ("test", "interview"),
        ("interview", "offer"),
    ]
    times = [e["at"] for e in body["timeline"]]
    assert times == sorted(times)


async def test_illegal_move_is_409_and_changes_nothing(
    admin: httpx.AsyncClient, student: httpx.AsyncClient
) -> None:
    drive = await publish(admin)
    await put(student, drive["id"], status="applied")

    response = await put(student, drive["id"], status="offer")  # skips test + interview

    assert response.status_code == 409
    assert response.json()["detail"] == "Can't move from applied to offer"
    tracker = (await student.get("/me/applications")).json()
    assert tracker[0]["status"] == "applied"
    assert moves(tracker[0]) == [(None, "applied")]


@pytest.mark.parametrize("final", ["offer", "rejected", "withdrawn"])
async def test_final_states_cannot_be_left(
    admin: httpx.AsyncClient, student: httpx.AsyncClient, final: str
) -> None:
    drive = await publish(admin)
    path = {"offer": ["applied", "interview", "offer"], "rejected": ["applied", "rejected"]}
    for status in path.get(final, ["interested", "withdrawn"]):
        assert (await put(student, drive["id"], status=status)).status_code == 200

    response = await put(student, drive["id"], status="applied")

    assert response.status_code == 409


async def test_tracking_must_start_at_interested_or_applied(
    admin: httpx.AsyncClient, student: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    drive = await publish(admin)

    response = await put(student, drive["id"], status="interview")

    assert response.status_code == 409
    assert response.json()["detail"] == "Start tracking with applied or interested"
    assert await db_session.scalar(select(func.count()).select_from(Application)) == 0


async def test_applied_can_go_straight_to_interview(
    admin: httpx.AsyncClient, student: httpx.AsyncClient
) -> None:
    drive = await publish(admin)
    await put(student, drive["id"], status="applied")

    response = await put(student, drive["id"], status="interview")  # no test round

    assert response.status_code == 200


# ---------------------------------------------------------------- notes and repeats


async def test_same_status_again_only_updates_notes_and_adds_no_event(
    admin: httpx.AsyncClient, student: httpx.AsyncClient
) -> None:
    drive = await publish(admin)
    await put(student, drive["id"], status="applied", notes="Applied via portal")

    response = await put(student, drive["id"], status="applied", notes="Test on Friday")

    body = response.json()
    assert body["notes"] == "Test on Friday"
    assert moves(body) == [(None, "applied")]


async def test_omitting_notes_keeps_them_and_null_clears_them(
    admin: httpx.AsyncClient, student: httpx.AsyncClient
) -> None:
    drive = await publish(admin)
    await put(student, drive["id"], status="applied", notes="  keep me  ")

    kept = (await put(student, drive["id"], status="test")).json()
    cleared = (await put(student, drive["id"], status="test", notes=None)).json()

    assert kept["notes"] == "keep me"  # trimmed, and untouched by a move without notes
    assert cleared["notes"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"status": "hired"},
        {},
        {"status": "applied", "notes": "x" * 2001},
        {"status": "applied", "x": 1},
    ],
)
async def test_invalid_bodies_are_422(
    admin: httpx.AsyncClient, student: httpx.AsyncClient, body: dict[str, Any]
) -> None:
    drive = await publish(admin)

    response = await student.put(f"/drives/{drive['id']}/application", json=body)

    assert response.status_code == 422


# ---------------------------------------------------------------- which drives


async def test_drafts_and_unknown_drives_are_404(
    admin: httpx.AsyncClient, student: httpx.AsyncClient
) -> None:
    draft = await create(admin)

    assert (await put(student, draft["id"], status="applied")).status_code == 404
    unknown = "00000000-0000-0000-0000-000000000000"
    assert (await put(student, unknown, status="applied")).status_code == 404


async def test_expired_and_closed_drives_stay_trackable(
    admin: httpx.AsyncClient, student: httpx.AsyncClient
) -> None:
    # Tests and interviews happen after the application deadline.
    drive = await publish(admin)
    await put(student, drive["id"], status="applied")
    await admin.patch(f"/admin/drives/{drive['id']}", json={"deadline": iso(timedelta(hours=-1))})

    assert (await put(student, drive["id"], status="test")).status_code == 200
    await admin.patch(f"/admin/drives/{drive['id']}", json={"status": "closed"})
    assert (await put(student, drive["id"], status="interview")).status_code == 200


async def test_tracking_needs_login(admin: httpx.AsyncClient, api: httpx.AsyncClient) -> None:
    drive = await publish(admin)

    assert (await put(api, drive["id"], status="applied")).status_code == 401
    assert (await api.get("/me/applications")).status_code == 401


# ---------------------------------------------------------------- GET /me/applications


async def test_tracker_lists_my_drives_with_their_state(
    admin: httpx.AsyncClient, student: httpx.AsyncClient
) -> None:
    older = await publish(admin, company="Older Co")
    newer = await publish(admin, company="Newer Co")
    await put(student, older["id"], status="applied")
    await put(student, newer["id"], status="interested")
    await admin.patch(f"/admin/drives/{older['id']}", json={"status": "closed"})

    tracker = (await student.get("/me/applications")).json()

    assert [t["drive"]["company"] for t in tracker] == ["Newer Co", "Older Co"]
    assert tracker[1]["drive"]["state"] == "closed"  # history stays visible
    assert tracker[1]["status"] == "applied"


async def test_each_student_sees_only_their_own_tracker(
    admin: httpx.AsyncClient,
    student: httpx.AsyncClient,
    settings: Settings,
    db_session: AsyncSession,
) -> None:
    drive = await publish(admin)
    await put(student, drive["id"], status="applied")

    async with api_client(settings, db_session) as other:
        await sign_in(other, "other@example.com")
        assert (await other.get("/me/applications")).json() == []
        # Their own tracker for the same drive is separate.
        assert (await put(other, drive["id"], status="interested")).status_code == 200

    assert (await student.get("/me/applications")).json()[0]["status"] == "applied"


# ---------------------------------------------------------------- concurrency


async def test_parallel_requests_create_one_tracker_and_record_each_move_once(
    settings: Settings, test_database_url: str
) -> None:
    """Real parallel transactions on separate connections (a double click, or two tabs).

    Not inside the rolled-back test transaction: each session must really commit for the
    row lock and ON CONFLICT to matter. The rows are deleted at the end (cascade).
    """
    engine = create_engine(with_database_url(settings, test_database_url))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    no_login = "-"
    user = User(email=f"race-{uuid.uuid4().hex}@example.com", password_hash=no_login, name="Race")
    drive = Drive(
        company="Race Co",
        role_title="SDE",
        deadline=datetime.now(UTC) + timedelta(days=3),
        raw_text="notice",
        status="published",
    )
    async with sessions() as setup:
        setup.add_all([user, drive])
        await setup.commit()

    async def request(status: str) -> str:
        async with sessions() as session:
            return (await set_status(session, user.id, drive.id, status)).status

    try:
        started = await asyncio.gather(*(request("applied") for _ in range(3)))
        moved = await asyncio.gather(*(request("test") for _ in range(3)))

        async with sessions() as check:
            apps = (
                await check.scalars(select(Application).where(Application.student_id == user.id))
            ).all()
            events = (
                await check.scalars(
                    select(ApplicationEvent.to_status)
                    .where(ApplicationEvent.application_id == apps[0].id)
                    .order_by(ApplicationEvent.at)
                )
            ).all()
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(delete(Drive).where(Drive.id == drive.id))
            await cleanup.execute(delete(User).where(User.id == user.id))
            await cleanup.commit()
        await engine.dispose()

    assert started == ["applied"] * 3 and moved == ["test"] * 3
    assert len(apps) == 1  # one tracker, not three
    assert events == ["applied", "test"]  # each move recorded exactly once
