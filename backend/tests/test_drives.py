"""Drives end to end over HTTP (real Postgres): admin CRUD, status rules, the student feed.

Day 3 "done when": an admin publishes a drive; the feed shows eligible / ineligible
drives with reasons.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Drive, DriveEligibility
from tests.conftest import api_client
from tests.helpers import profile, sign_in, sign_in_as_admin

pytestmark = [pytest.mark.anyio, pytest.mark.db]


def iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).isoformat()


def new_drive(**overrides: Any) -> dict[str, Any]:
    return {
        "company": "Acme Corp",
        "role_title": "Software Engineer",
        "deadline": iso(timedelta(days=7)),
        "raw_text": "Acme Corp is hiring Software Engineers. Apply by next week.",
    } | overrides


@pytest.fixture
async def admin(settings: Settings, db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    async with api_client(settings, db_session) as client:
        await sign_in_as_admin(client, db_session)
        yield client


@pytest.fixture
async def student(settings: Settings, db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """A logged-in student with a profile: CSE, CGPA 7.5, no backlogs, 2027."""
    async with api_client(settings, db_session) as client:
        await sign_in(client, "student@example.com")
        assert (await client.put("/me/profile", json=profile())).status_code == 200
        yield client


async def create(admin: httpx.AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await admin.post("/admin/drives", json=new_drive(**overrides))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def publish(admin: httpx.AsyncClient, **overrides: Any) -> dict[str, Any]:
    drive = await create(admin, **overrides)
    response = await admin.patch(f"/admin/drives/{drive['id']}", json={"status": "published"})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# ---------------------------------------------------------------- access control


async def test_admin_routes_need_login(api: httpx.AsyncClient) -> None:
    assert (await api.get("/admin/drives")).status_code == 401
    assert (await api.post("/admin/drives", json=new_drive())).status_code == 401


async def test_students_get_403_on_every_admin_route(student: httpx.AsyncClient) -> None:
    some_id = "00000000-0000-0000-0000-000000000000"
    responses = [
        await student.get("/admin/drives"),
        await student.post("/admin/drives", json=new_drive()),
        await student.get(f"/admin/drives/{some_id}"),
        await student.patch(f"/admin/drives/{some_id}", json={"status": "published"}),
    ]

    assert [r.status_code for r in responses] == [403, 403, 403, 403]


# ---------------------------------------------------------------- create


async def test_create_makes_a_draft_with_normalised_rules(
    admin: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    body = await create(
        admin,
        ctc_text="12 LPA + joining bonus",
        ctc_lpa="12.5",
        apply_link="https://careers.example.com/apply",
        source="email",
        eligibility={
            "min_cgpa": 7,
            "max_active_backlogs": 0,
            "grad_years": [2027, 2026, 2027],
            "allowed_branches": ["it", " cse", "IT"],
        },
    )

    assert body["status"] == "draft"
    assert body["state"] == "draft"
    assert body["ctc_lpa"] == 12.5
    assert body["eligibility"] == {
        "min_cgpa": 7.0,
        "max_active_backlogs": 0,
        "grad_years": [2026, 2027],  # sorted, de-duplicated
        "allowed_branches": ["CSE", "IT"],  # upper-cased, sorted, de-duplicated
    }
    stored = await db_session.scalar(select(Drive))
    assert stored is not None
    assert stored.created_by is not None


async def test_no_rules_stores_an_all_null_rules_row(
    admin: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    body = await create(admin)

    rules = await db_session.scalar(select(DriveEligibility))
    assert rules is not None
    assert (rules.min_cgpa, rules.max_active_backlogs, rules.grad_years) == (None, None, None)
    assert body["eligibility"] == {
        "min_cgpa": None,
        "max_active_backlogs": None,
        "grad_years": [],
        "allowed_branches": [],
    }


async def test_deadline_without_timezone_is_read_as_ist(admin: httpx.AsyncClient) -> None:
    body = await create(admin, deadline="2030-12-01T17:00:00")

    assert body["deadline"] == "2030-12-01T11:30:00Z"  # 17:00 IST = 11:30 UTC


async def test_deadline_with_an_offset_is_converted_to_utc(admin: httpx.AsyncClient) -> None:
    body = await create(admin, deadline="2030-12-01T17:00:00+05:30")

    assert body["deadline"] == "2030-12-01T11:30:00Z"


async def test_unknown_branch_codes_are_rejected_by_name(admin: httpx.AsyncClient) -> None:
    response = await admin.post(
        "/admin/drives",
        json=new_drive(eligibility={"allowed_branches": ["CSE", "XYZ", "ABC"]}),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown branch codes: ABC, XYZ"


@pytest.mark.parametrize(
    "overrides",
    [
        {"apply_link": "javascript:alert(1)"},  # would run in the student's browser
        {"company": "   "},
        {"raw_text": ""},
        {"ctc_lpa": -1},
        {"source": "fax"},
        {"eligibility": {"min_cgpa": 10.5}},
        {"eligibility": {"max_active_backlogs": -1}},
        {"eligibility": {"grad_years": [1999]}},
        {"status": "published"},  # create can't skip the draft step
        {"unexpected": "field"},
    ],
)
async def test_invalid_drives_are_rejected(
    admin: httpx.AsyncClient, overrides: dict[str, Any]
) -> None:
    response = await admin.post("/admin/drives", json=new_drive(**overrides))

    assert response.status_code == 422


# ---------------------------------------------------------------- edit, publish, close


async def test_publish_then_close(admin: httpx.AsyncClient) -> None:
    published = await publish(admin)
    assert (published["status"], published["state"]) == ("published", "open")
    assert published["closed_at"] is None

    response = await admin.patch(f"/admin/drives/{published['id']}", json={"status": "closed"})

    closed = response.json()
    assert (closed["status"], closed["state"]) == ("closed", "closed")
    assert closed["closed_at"] is not None


async def test_publishing_with_a_past_deadline_is_rejected_and_changes_nothing(
    admin: httpx.AsyncClient,
) -> None:
    drive = await create(admin, deadline=iso(timedelta(days=-1)))

    response = await admin.patch(
        f"/admin/drives/{drive['id']}", json={"status": "published", "company": "Renamed"}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Can't publish: the deadline has passed"
    after = (await admin.get(f"/admin/drives/{drive['id']}")).json()
    assert (after["status"], after["company"]) == ("draft", "Acme Corp")


async def test_fixing_the_deadline_and_publishing_in_one_request(
    admin: httpx.AsyncClient,
) -> None:
    drive = await create(admin, deadline=iso(timedelta(days=-1)))

    response = await admin.patch(
        f"/admin/drives/{drive['id']}",
        json={"status": "published", "deadline": iso(timedelta(days=3))},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "open"


async def test_a_draft_cannot_be_closed(admin: httpx.AsyncClient) -> None:
    # A draft was never visible to students, so "closed" (cancelled/filled) makes no sense.
    drive = await create(admin)

    response = await admin.patch(f"/admin/drives/{drive['id']}", json={"status": "closed"})

    assert response.status_code == 409
    assert response.json()["detail"] == "Can't change a draft drive to closed"


async def test_a_closed_drive_cannot_be_republished(admin: httpx.AsyncClient) -> None:
    drive = await publish(admin)
    await admin.patch(f"/admin/drives/{drive['id']}", json={"status": "closed"})

    response = await admin.patch(f"/admin/drives/{drive['id']}", json={"status": "published"})

    assert response.status_code == 409


async def test_a_closed_drive_cannot_be_edited(admin: httpx.AsyncClient) -> None:
    drive = await publish(admin)
    await admin.patch(f"/admin/drives/{drive['id']}", json={"status": "closed"})

    response = await admin.patch(f"/admin/drives/{drive['id']}", json={"company": "New"})

    assert response.status_code == 409
    assert response.json()["detail"] == "A closed drive can't be changed"


async def test_patch_changes_only_the_fields_sent(admin: httpx.AsyncClient) -> None:
    drive = await create(admin, location="Bengaluru", ctc_text="10 LPA")

    response = await admin.patch(
        f"/admin/drives/{drive['id']}", json={"location": None, "role_title": "SDE 1"}
    )

    body = response.json()
    assert body["location"] is None  # null clears an optional field
    assert body["role_title"] == "SDE 1"
    assert body["ctc_text"] == "10 LPA"  # not sent, so unchanged
    assert body["company"] == "Acme Corp"


@pytest.mark.parametrize("field", ["company", "role_title", "deadline", "raw_text", "status"])
async def test_patch_cannot_clear_a_required_field(admin: httpx.AsyncClient, field: str) -> None:
    drive = await create(admin)

    response = await admin.patch(f"/admin/drives/{drive['id']}", json={field: None})

    assert response.status_code == 422


async def test_patch_eligibility_replaces_the_whole_rule_set(admin: httpx.AsyncClient) -> None:
    drive = await create(admin, eligibility={"min_cgpa": 8, "allowed_branches": ["CSE", "IT"]})

    response = await admin.patch(
        f"/admin/drives/{drive['id']}",
        json={"eligibility": {"allowed_branches": ["IT", "ECE"]}},  # IT kept, CSE dropped
    )

    assert response.status_code == 200
    assert response.json()["eligibility"] == {
        "min_cgpa": None,  # not sent → no longer a rule
        "max_active_backlogs": None,
        "grad_years": [],
        "allowed_branches": ["ECE", "IT"],
    }


async def test_patch_with_unknown_branch_is_422(admin: httpx.AsyncClient) -> None:
    drive = await create(admin)

    response = await admin.patch(
        f"/admin/drives/{drive['id']}", json={"eligibility": {"allowed_branches": ["XYZ"]}}
    )

    assert response.status_code == 422


async def test_unknown_drive_is_404_for_admins(admin: httpx.AsyncClient) -> None:
    some_id = "00000000-0000-0000-0000-000000000000"

    assert (await admin.get(f"/admin/drives/{some_id}")).status_code == 404
    assert (await admin.patch(f"/admin/drives/{some_id}", json={})).status_code == 404


async def test_admin_list_includes_drafts(admin: httpx.AsyncClient) -> None:
    draft = await create(admin, company="Draft Co")
    published = await publish(admin, company="Live Co")

    body = (await admin.get("/admin/drives")).json()

    assert {d["id"] for d in body} == {draft["id"], published["id"]}


# ---------------------------------------------------------------- student feed


async def test_feed_is_locked_until_the_profile_is_saved(api: httpx.AsyncClient) -> None:
    await sign_in(api)

    response = await api.get("/drives")

    assert response.status_code == 409
    assert response.json()["detail"] == "Complete your profile to see drives"


async def test_feed_needs_login(api: httpx.AsyncClient) -> None:
    assert (await api.get("/drives")).status_code == 401


async def test_feed_shows_eligible_first_then_ineligible_with_reasons(
    admin: httpx.AsyncClient, student: httpx.AsyncClient
) -> None:
    """Day 3 "done when": admin publishes; the feed shows eligibility with reasons."""
    later = await publish(admin, company="Later Co", deadline=iso(timedelta(days=9)))
    sooner = await publish(admin, company="Sooner Co", deadline=iso(timedelta(days=2)))
    strict = await publish(
        admin,
        company="Strict Co",
        deadline=iso(timedelta(days=1)),  # soonest, but ineligible → listed last
        eligibility={"min_cgpa": 8, "allowed_branches": ["ECE"]},
    )
    at_cutoff = await publish(
        admin, company="Cutoff Co", deadline=iso(timedelta(days=5)), eligibility={"min_cgpa": 7.5}
    )

    response = await student.get("/drives")

    assert response.status_code == 200
    feed = response.json()
    assert [d["id"] for d in feed] == [sooner["id"], at_cutoff["id"], later["id"], strict["id"]]
    assert [d["eligible"] for d in feed] == [True, True, True, False]
    assert feed[1]["reasons"] == []  # CGPA exactly at the cutoff is eligible
    assert feed[3]["reasons"] == ["Open to ECE only (you: CSE)", "Needs CGPA ≥ 8 (you: 7.5)"]
    assert all(d["state"] == "open" for d in feed)
    assert "raw_text" not in feed[0]  # only on the detail page


async def test_feed_hides_drafts_closed_and_expired_drives(
    admin: httpx.AsyncClient, student: httpx.AsyncClient
) -> None:
    await create(admin, company="Draft Co")
    closed = await publish(admin, company="Closed Co")
    await admin.patch(f"/admin/drives/{closed['id']}", json={"status": "closed"})
    expired = await publish(admin, company="Expired Co")
    await admin.patch(f"/admin/drives/{expired['id']}", json={"deadline": iso(timedelta(hours=-1))})
    live = await publish(admin, company="Live Co")

    feed = (await student.get("/drives")).json()

    assert [d["id"] for d in feed] == [live["id"]]


async def test_expiry_is_computed_so_extending_the_deadline_reopens(
    admin: httpx.AsyncClient, student: httpx.AsyncClient
) -> None:
    drive = await publish(admin)
    url = f"/admin/drives/{drive['id']}"

    expired = (await admin.patch(url, json={"deadline": iso(timedelta(hours=-1))})).json()
    assert (expired["status"], expired["state"]) == ("published", "expired")  # stored vs shown
    assert (await student.get("/drives")).json() == []

    reopened = (await admin.patch(url, json={"deadline": iso(timedelta(days=2))})).json()
    assert reopened["state"] == "open"
    assert [d["id"] for d in (await student.get("/drives")).json()] == [drive["id"]]


# ---------------------------------------------------------------- student drive page


async def test_student_drive_page_has_notice_text_and_eligibility(
    admin: httpx.AsyncClient, student: httpx.AsyncClient
) -> None:
    drive = await publish(admin, eligibility={"grad_years": [2026]})

    response = await student.get(f"/drives/{drive['id']}")

    body = response.json()
    assert response.status_code == 200
    assert body["raw_text"] == new_drive()["raw_text"]
    assert body["eligible"] is False
    assert body["reasons"] == ["For the 2026 batch only (you: 2027)"]


async def test_students_cannot_see_drafts(
    admin: httpx.AsyncClient, student: httpx.AsyncClient
) -> None:
    draft = await create(admin)

    assert (await student.get(f"/drives/{draft['id']}")).status_code == 404


async def test_closed_drives_stay_reachable_for_history(
    admin: httpx.AsyncClient, student: httpx.AsyncClient
) -> None:
    drive = await publish(admin)
    await admin.patch(f"/admin/drives/{drive['id']}", json={"status": "closed"})

    response = await student.get(f"/drives/{drive['id']}")

    assert response.status_code == 200
    assert response.json()["state"] == "closed"


async def test_drive_page_needs_a_profile(
    admin: httpx.AsyncClient, settings: Settings, db_session: AsyncSession
) -> None:
    drive = await publish(admin)
    async with api_client(settings, db_session) as no_profile:
        await sign_in(no_profile, "new@example.com")

        response = await no_profile.get(f"/drives/{drive['id']}")

    assert response.status_code == 409
