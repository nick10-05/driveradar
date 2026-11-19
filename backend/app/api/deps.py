"""Shared FastAPI dependencies.

Interview notes:
- One AsyncSession per request, from the sessionmaker the lifespan created. It is closed
  when the request ends, which returns the connection to the pool.
- Handlers commit explicitly. Nothing is committed by accident: if a handler raises, the
  session closes without committing and the transaction is rolled back.
- Tests override `get_session` to hand in a session bound to a transaction they roll back.
"""

from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.rate_limit import AuthLimiters
from app.models import User
from app.services.auth import user_for_token


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(get_settings)]


def get_auth_limiters(request: Request) -> AuthLimiters:
    limiters: AuthLimiters = request.app.state.auth_limiters
    return limiters


Limiters = Annotated[AuthLimiters, Depends(get_auth_limiters)]


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_session)]


async def current_user(request: Request, session: DbSession, settings: AppSettings) -> User:
    """The logged-in user, from the session cookie. 401 if missing, unknown or expired."""
    token = request.cookies.get(settings.session_cookie_name)
    user = await user_for_token(session, token) if token else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    # Every later log line in this request says who it was (cleared after the request).
    structlog.contextvars.bind_contextvars(user_id=str(user.id))
    return user


CurrentUser = Annotated[User, Depends(current_user)]
