"""Make an existing user an admin (DESIGN §3: there is no self-service admin signup).

    DATABASE_URL=... uv run python -m app.scripts.promote_admin someone@example.com

Only DATABASE_URL is needed (not the whole app config), so it can be run from a laptop
against Neon. The user must have registered first. Running it twice is harmless.

Interview notes:
- Admin rights never come from an HTTP request: no endpoint can grant them, so a bug or
  a stolen student session can't escalate to admin.
"""

import asyncio
import os
import ssl
import sys

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import normalize_database_url
from app.models import User


async def promote(session: AsyncSession, email: str) -> bool:
    """Set role='admin' for this email. False if no such user."""
    result = await session.execute(
        update(User).where(User.email == email.strip().lower()).values(role="admin")
    )
    await session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def _main(email: str) -> int:
    url, ssl_required = normalize_database_url(os.environ["DATABASE_URL"])
    connect_args = {"ssl": ssl.create_default_context()} if ssl_required else {}
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with AsyncSession(engine) as session:
            found = await promote(session, email)
    finally:
        await engine.dispose()
    print("Promoted to admin." if found else "No user with that email. Register first.")
    return 0 if found else 1


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    if len(sys.argv) != 2 or "DATABASE_URL" not in os.environ:
        sys.exit("usage: DATABASE_URL=... python -m app.scripts.promote_admin <email>")
    sys.exit(asyncio.run(_main(sys.argv[1])))
