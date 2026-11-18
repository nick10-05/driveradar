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

from app.api import health
from app.core.config import Settings
from app.core.db import create_engine, create_sessionmaker
from app.core.logging import configure_logging
from app.core.request_id import RequestIdMiddleware


def create_app(settings: Settings) -> FastAPI:
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.settings = settings
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="DriveRadar API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)
    return app
