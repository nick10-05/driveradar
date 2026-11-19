"""POST /admin/drives/extract end to end (real Postgres, FakeExtractor; never a real LLM).

Day 4 "done when": a pasted notice gives a flagged draft; manual fallback works with
LLM_PROVIDER=none.
"""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.rate_limit import SlidingWindowLimiter
from app.models import Drive, ExtractionRun
from app.services.extraction.prompt import PROMPT_VERSION
from app.services.extraction.schema import ExtractedNotice, ExtractionResult
from tests.conftest import api_client
from tests.fakes import FakeExtractor
from tests.helpers import sign_in, sign_in_as_admin

pytestmark = [pytest.mark.anyio, pytest.mark.db]

NOTICE = """Globex Ltd is hiring Data Analysts (2027 batch).
CTC 8 LPA. Open to CSE and Mechatronics. Minimum CGPA 7.
Apply by 10 Dec 2026, 6 PM: https://globex.example/jobs"""

AI_ANSWER = ExtractedNotice(
    company="Globex Ltd",
    role_title="Data Analyst",
    ctc_text="8 LPA",
    ctc_lpa=8,
    apply_link="https://globex.example/jobs",
    deadline_text="10 Dec 2026, 6 PM",
    deadline_local="2026-12-10T18:00:00",
    min_cgpa=7.5,  # the notice says 7: the evidence check must catch this
    branches_raw=["CSE", "Mechatronics"],  # Mechatronics isn't a known branch
    grad_years=[2027],
    evidence={
        "company": "Globex Ltd is hiring",
        "deadline": "Apply by 10 Dec 2026, 6 PM",
        "ctc": "CTC 8 LPA",
        "min_cgpa": "Minimum CGPA 7",
        "branches": "Open to CSE and Mechatronics",
        "grad_years": "(2027 batch)",
    },
)


def ok(notice: ExtractedNotice = AI_ANSWER, **extra: Any) -> ExtractionResult:
    return ExtractionResult(status="ok", notice=notice, model="fake-model", **extra)


@pytest.fixture
async def admin_with(settings: Settings, db_session: AsyncSession) -> AsyncIterator[Any]:
    """Factory: an admin client whose app uses the given extractor."""
    clients: list[Any] = []

    async def make(
        extractor: Any, limiter: SlidingWindowLimiter | None = None
    ) -> httpx.AsyncClient:
        context = api_client(settings, db_session, extractor=extractor, extraction_limiter=limiter)
        client = await context.__aenter__()
        clients.append(context)
        await sign_in_as_admin(client, db_session)
        return client

    yield make
    for context in reversed(clients):
        await context.__aexit__(None, None, None)


async def extract(client: httpx.AsyncClient, raw_text: str = NOTICE) -> httpx.Response:
    return await client.post("/admin/drives/extract", json={"raw_text": raw_text})


# ---------------------------------------------------------------- done when


async def test_a_pasted_notice_gives_a_flagged_draft(
    admin_with: Any, db_session: AsyncSession
) -> None:
    fake = FakeExtractor(ok(input_tokens=700, output_tokens=120))
    admin = await admin_with(fake)

    response = await extract(admin)

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["model"]) == ("ok", "fake-model")
    draft = body["draft"]
    assert draft["company"] == "Globex Ltd"
    assert draft["deadline"] == "2026-12-10T12:30:00Z"  # 18:00 IST
    assert draft["ctc_lpa"] == 8.0
    assert draft["eligibility"]["allowed_branches"] == ["CSE"]
    flags = {(i["field"], i["kind"]) for i in body["issues"]}
    assert ("eligibility.min_cgpa", "verify") in flags  # 7.5 isn't in "Minimum CGPA 7"
    assert ("eligibility.allowed_branches", "invalid") in flags  # Mechatronics
    assert fake.calls == [NOTICE]  # only the notice text was sent: no student data

    run = await db_session.scalar(select(ExtractionRun))
    assert run is not None
    assert (run.status, run.provider, run.model) == ("ok", "none", "fake-model")
    assert run.prompt_version == PROMPT_VERSION
    assert (run.input_tokens, run.output_tokens) == (700, 120)
    assert run.latency_ms is not None
    assert run.output_json is not None
    assert run.output_json["company"] == "Globex Ltd"
    assert len(run.issues) == len(body["issues"])
    assert str(run.id) == body["extraction_run_id"]


async def test_manual_fallback_with_provider_none(
    api: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # The real dependency (no override): settings say LLM_PROVIDER=none.
    await sign_in_as_admin(api, db_session)

    response = await extract(api)

    body = response.json()
    assert response.status_code == 200
    assert (body["status"], body["provider"], body["model"]) == ("disabled", "none", None)
    assert body["issues"] == []
    assert body["draft"]["company"] is None  # an empty form to fill by hand
    run = await db_session.scalar(select(ExtractionRun))
    assert run is not None
    assert (run.status, run.output_json) == ("disabled", None)


@pytest.mark.parametrize(
    "result",
    [
        ExtractionResult(status="error", error="timeout", model="m"),
        ExtractionResult(status="error", error="http_429", model="m"),
        ExtractionResult(status="invalid", error="invalid_output", model="m"),
    ],
)
async def test_ai_failures_still_return_an_empty_form(
    admin_with: Any, db_session: AsyncSession, result: ExtractionResult
) -> None:
    admin = await admin_with(FakeExtractor(result))

    response = await extract(admin)

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == result.status
    assert body["draft"]["company"] is None
    run = await db_session.scalar(select(ExtractionRun))
    assert run is not None
    assert run.error == result.error


async def test_even_a_crashing_extractor_falls_back_to_manual(
    admin_with: Any, db_session: AsyncSession
) -> None:
    class Broken:
        async def extract(self, raw_text: str) -> ExtractionResult:
            raise RuntimeError("bug in an adapter")

    admin = await admin_with(Broken())

    response = await extract(admin)

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    run = await db_session.scalar(select(ExtractionRun))
    assert run is not None
    assert run.error == "unexpected"


async def test_extract_saves_no_drive(admin_with: Any, db_session: AsyncSession) -> None:
    admin = await admin_with(FakeExtractor(ok()))

    await extract(admin)

    assert await db_session.scalar(select(func.count()).select_from(Drive)) == 0


# ---------------------------------------------------------------- linking the drive


async def test_saving_the_reviewed_draft_links_the_run(admin_with: Any) -> None:
    admin = await admin_with(FakeExtractor(ok()))
    body = (await extract(admin)).json()
    draft = body["draft"]

    response = await admin.post(
        "/admin/drives",
        json={
            "company": draft["company"],
            "role_title": draft["role_title"],
            "deadline": draft["deadline"],
            "raw_text": NOTICE,
            "eligibility": draft["eligibility"] | {"min_cgpa": 7},  # admin fixes the flag
            "extraction_run_id": body["extraction_run_id"],
        },
    )

    assert response.status_code == 201
    assert response.json()["extraction_run_id"] == body["extraction_run_id"]


async def test_an_unknown_extraction_run_id_is_rejected(admin_with: Any) -> None:
    admin = await admin_with(FakeExtractor(ok()))

    response = await admin.post(
        "/admin/drives",
        json={
            "company": "X",
            "role_title": "Y",
            "deadline": "2030-01-01T10:00:00Z",
            "raw_text": "notice",
            "extraction_run_id": "00000000-0000-0000-0000-000000000000",
        },
    )

    assert response.status_code == 422


# ---------------------------------------------------------------- limits and access


async def test_extraction_is_rate_limited_per_admin(admin_with: Any) -> None:
    admin = await admin_with(FakeExtractor(ok()), SlidingWindowLimiter(2, 3600))

    statuses = [(await extract(admin)).status_code for _ in range(3)]

    assert statuses == [200, 200, 429]


@pytest.mark.parametrize("raw_text", ["", "   ", "x" * 8_001])
async def test_notice_length_is_bounded(admin_with: Any, raw_text: str) -> None:
    fake = FakeExtractor(ok())
    admin = await admin_with(fake)

    response = await extract(admin, raw_text)

    assert response.status_code == 422
    assert fake.calls == []  # rejected before any AI call


async def test_students_cannot_extract(api: httpx.AsyncClient) -> None:
    await sign_in(api)

    assert (await extract(api)).status_code == 403
