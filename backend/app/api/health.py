"""Liveness and readiness probes.

Interview notes:
- /healthz answers "is the process alive?" and never touches the DB. A platform that
  restarts unhealthy processes must not restart the app just because the DB blipped.
- /readyz answers "can this instance serve traffic?" and checks the DB. 503 tells a load
  balancer or uptime monitor to wait, without killing the process.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from app.core.db import check_database

router = APIRouter(tags=["health"])


class HealthStatus(BaseModel):
    status: Literal["ok", "unavailable"]


async def database_ready(request: Request) -> bool:
    """Dependency so tests can override the DB check without a real database."""
    return await check_database(request.app.state.engine)


@router.get("/healthz")
async def healthz() -> HealthStatus:
    return HealthStatus(status="ok")


@router.get(
    "/readyz",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthStatus}},
)
async def readyz(
    db_ok: Annotated[bool, Depends(database_ready)], response: Response
) -> HealthStatus:
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatus(status="unavailable")
    return HealthStatus(status="ok")
