"""Drive request/response models (DESIGN §5 F2/F3, §8).

Interview notes:
- Deadlines: an ISO time with an offset is converted to UTC. One without an offset is
  assumed to be IST (Indian notices rarely say "IST"), never UTC: assuming UTC would
  silently move every deadline 5h30m later. India has no DST, so a fixed +05:30 offset
  is exact (and needs no tz database in the slim Docker image).
- apply_link must be an http(s) URL. A `javascript:` link would run in a student's browser
  when clicked, so it is rejected at the edge.
- PATCH semantics: only the fields sent are changed. Sending null clears an optional
  field (e.g. location) but is rejected for a required one (e.g. company).
  `eligibility`, when sent, replaces the whole rule set: rules are small and editing them
  as one unit avoids "which rule did that PATCH mean to remove?" questions.
- `state` (draft / open / expired / closed) is computed for the response; only
  draft / published / closed is stored.
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

from app.schemas.profile import BranchCode, Cgpa

IST = timezone(timedelta(hours=5, minutes=30), "IST")


def _to_utc_assuming_ist(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=IST)
    return value.astimezone(UTC)


def _sorted_unique[T: (int, str)](values: list[T]) -> list[T]:
    return sorted(set(values))


Deadline = Annotated[datetime, AfterValidator(_to_utc_assuming_ist)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
RawText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)]
CtcLpa = Annotated[
    Decimal,
    Field(ge=0, max_digits=6, decimal_places=2),
    PlainSerializer(float, return_type=float, when_used="json"),
]
GradYear = Annotated[int, Field(ge=2000, le=2100)]
Source = Literal["email", "whatsapp", "portal", "telegram", "other"]
DriveState = Literal["draft", "open", "expired", "closed"]


class EligibilityRulesIn(BaseModel):
    """Empty / null = no restriction."""

    model_config = ConfigDict(extra="forbid")

    min_cgpa: Cgpa | None = None
    max_active_backlogs: Annotated[int, Field(ge=0, le=100)] | None = None
    grad_years: Annotated[list[GradYear], Field(max_length=10), AfterValidator(_sorted_unique)] = []
    allowed_branches: Annotated[
        list[BranchCode], Field(max_length=50), AfterValidator(_sorted_unique)
    ] = []


class DriveCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: ShortText
    role_title: ShortText
    ctc_text: ShortText | None = None
    ctc_lpa: CtcLpa | None = None
    location: ShortText | None = None
    apply_link: HttpUrl | None = None
    deadline: Deadline
    source: Source | None = None
    raw_text: RawText
    eligibility: EligibilityRulesIn = EligibilityRulesIn()


_REQUIRED_ON_PATCH = ("company", "role_title", "deadline", "raw_text", "status", "eligibility")


class DriveUpdate(BaseModel):
    """PATCH /admin/drives/{id}: edit fields and/or publish / close."""

    model_config = ConfigDict(extra="forbid")

    company: ShortText | None = None
    role_title: ShortText | None = None
    ctc_text: ShortText | None = None
    ctc_lpa: CtcLpa | None = None
    location: ShortText | None = None
    apply_link: HttpUrl | None = None
    deadline: Deadline | None = None
    source: Source | None = None
    raw_text: RawText | None = None
    eligibility: EligibilityRulesIn | None = None
    status: Literal["published", "closed"] | None = None

    @model_validator(mode="after")
    def _required_fields_cannot_be_cleared(self) -> Self:
        cleared = [
            name
            for name in _REQUIRED_ON_PATCH
            if name in self.model_fields_set and getattr(self, name) is None
        ]
        if cleared:
            raise ValueError(f"cannot be null: {', '.join(cleared)}")
        return self


class EligibilityRulesOut(BaseModel):
    min_cgpa: Cgpa | None
    max_active_backlogs: int | None
    grad_years: list[int]
    allowed_branches: list[str]


class DriveFields(BaseModel):
    """What students and admins both see."""

    id: uuid.UUID
    company: str
    role_title: str
    ctc_text: str | None
    ctc_lpa: CtcLpa | None
    location: str | None
    apply_link: str | None
    deadline: datetime  # UTC; the frontend shows it in IST
    state: DriveState
    eligibility: EligibilityRulesOut


class AdminDriveOut(DriveFields):
    status: Literal["draft", "published", "closed"]
    source: str | None
    raw_text: str
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StudentDriveOut(DriveFields):
    """A feed entry: the drive plus this student's eligibility result."""

    eligible: bool
    reasons: list[str]


class StudentDriveDetailOut(StudentDriveOut):
    raw_text: str  # the original notice, only on the detail page (it can be long)
