"""App factory: builds a FastAPI app from Settings.

Interview notes:
- A factory (instead of a module-level app) lets tests create an app with their own
  settings, and keeps importing modules free of side effects like reading env vars.
- The lifespan owns shared resources: the DB engine is created on startup and disposed
  on shutdown, so connections close cleanly when Render stops the container.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth, branches, health, me
from app.core.config import Settings
from app.core.db import create_engine, create_sessionmaker
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.origin import OriginCheckMiddleware
from app.core.rate_limit import AuthLimiters
from app.core.request_id import RequestIdMiddleware


def create_app(settings: Settings) -> FastAPI:
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="DriveRadar API", version="0.1.0", lifespan=lifespan)
    # Settings are static, so they're set here rather than in the lifespan: available even
    # when a test drives the app without running startup.
    app.state.settings = settings
    # Per-app (not module-global) so every test app starts with empty counters.
    app.state.auth_limiters = AuthLimiters.default()
    # Starlette runs the LAST added middleware first: request IDs wrap everything, so even
    # a rejected-Origin response is logged with its request ID.
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.allowed_origins)
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(branches.router)
    return app
