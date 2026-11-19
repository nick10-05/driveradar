"""GET /branches: the branch codes students pick from in their profile.

Public on purpose: it's non-sensitive lookup data, and the frontend needs it to build the
profile form. Aliases stay internal (they're for the Day 4 normaliser, not the UI).
"""

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession
from app.models import Branch
from app.schemas.branch import BranchOut

router = APIRouter(tags=["branches"])


@router.get("/branches")
async def list_branches(session: DbSession) -> list[BranchOut]:
    rows = await session.scalars(select(Branch).order_by(Branch.code))
    return [BranchOut.model_validate(row) for row in rows]
