"""app.scripts.seed_demo: local-only guard, and the data it creates (real Postgres)."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Application, Drive, User
from app.scripts.seed_demo import ASHA, RAVI, UnsafeTargetError, check_target, seed
from tests.conftest import api_client

PASSWORD = "demo-password-for-tests"  # noqa: S105 - fake test value


def with_target(settings: Settings, environment: str, url: str) -> Settings:
    return settings.model_copy(update={"environment": environment, "database_url": SecretStr(url)})


class TestGuard:
    @pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "db"])
    def test_local_dev_database_is_allowed(self, settings: Settings, host: str) -> None:
        check_target(with_target(settings, "dev", f"postgresql+asyncpg://u:p@{host}:5432/d"))

    def test_remote_database_is_refused(self, settings: Settings) -> None:
        neon = "postgresql+asyncpg://u:p@ep-cool-name-123.ap-southeast-1.aws.neon.tech/neondb"

        with pytest.raises(UnsafeTargetError, match="local"):
            check_target(with_target(settings, "dev", neon))

    @pytest.mark.parametrize("environment", ["prod", "test"])
    def test_non_dev_environment_is_refused(self, settings: Settings, environment: str) -> None:
        local = with_target(settings, environment, "postgresql+asyncpg://u:p@localhost/d")

        with pytest.raises(UnsafeTargetError, match="dev"):
            check_target(local)


async def count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


@pytest.mark.anyio
@pytest.mark.db
class TestSeed:
    async def test_running_twice_gives_the_same_data(self, db_session: AsyncSession) -> None:
        before = [await count(db_session, m) for m in (User, Drive, Application)]

        first = await seed(db_session, PASSWORD)
        second = await seed(db_session, PASSWORD)

        assert first == second == {"users": 3, "drives": 8, "applications": 5}
        after = [await count(db_session, m) for m in (User, Drive, Application)]
        assert after == [before[0] + 3, before[1] + 8, before[2] + 5]

    async def test_demo_students_see_a_useful_feed(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        await seed(db_session, PASSWORD)

        async with api_client(settings, db_session) as client:
            login = await client.post("/auth/login", json={"email": ASHA, "password": PASSWORD})
            assert login.status_code == 200
            feed = (await client.get("/drives")).json()
            tracker = (await client.get("/me/applications")).json()

        companies = [d["company"] for d in feed]
        # Open drives only (no draft, closed or expired drives), eligible first.
        assert set(companies) == {
            "Zoho Corporation",
            "Razorpay",
            "Infosys",
            "Deloitte USI",
            "L&T Construction",
        }
        assert [d["company"] for d in feed if not d["eligible"]] == ["L&T Construction"]
        assert companies[-1] == "L&T Construction"
        assert len(tracker) == 4

        async with api_client(settings, db_session) as client:
            login = await client.post("/auth/login", json={"email": RAVI, "password": PASSWORD})
            assert login.status_code == 200
            ravi_feed = (await client.get("/drives")).json()
        assert sum(not d["eligible"] for d in ravi_feed) >= 3  # sees the reasons

    async def test_urgent_drive_closes_within_a_day(self, db_session: AsyncSession) -> None:
        now = datetime.now(UTC)

        await seed(db_session, PASSWORD, now=now)

        razorpay = await db_session.scalar(select(Drive).where(Drive.company == "Razorpay"))
        assert razorpay is not None
        assert razorpay.deadline - now == timedelta(hours=18)
