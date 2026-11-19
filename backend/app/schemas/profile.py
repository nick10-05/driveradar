"""Student profile request/response models (DESIGN §5 F1).

Interview notes:
- CGPA is a Decimal with at most 2 decimal places, matching NUMERIC(4,2) in the DB, so
  what the student typed is exactly what eligibility compares against a cutoff.
  In JSON responses it is sent as a number (7.5), which is what the frontend expects.
- The branch code is normalised (trimmed, upper-cased) and then checked against the
  `branches` table by the service, so the error says "unknown branch", not a raw DB error.
"""

import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints

from app.models import StudentProfile

Cgpa = Annotated[
    Decimal,
    Field(ge=0, le=10, max_digits=4, decimal_places=2),
    PlainSerializer(float, return_type=float, when_used="json"),
]
BranchCode = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=16)
]


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_code: BranchCode
    cgpa: Cgpa
    active_backlogs: int = Field(ge=0, le=100)
    grad_year: int = Field(ge=2000, le=2100)


class ProfileOut(BaseModel):
    branch_code: str
    cgpa: Cgpa
    active_backlogs: int
    grad_year: int
    telegram_linked: bool  # derived; the chat id itself is never sent to the browser

    @classmethod
    def from_model(cls, profile: StudentProfile) -> "ProfileOut":
        return cls(
            branch_code=profile.branch_code,
            cgpa=profile.cgpa,
            active_backlogs=profile.active_backlogs,
            grad_year=profile.grad_year,
            telegram_linked=profile.telegram_chat_id is not None,
        )


class MeOut(BaseModel):
    """GET /me. `profile` is null until the student saves one (the feed stays locked)."""

    id: uuid.UUID
    email: str
    name: str
    role: str
    profile: ProfileOut | None
