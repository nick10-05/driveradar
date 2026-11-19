"""Tracker request/response models (DESIGN §5 F4, §8)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.drive import DriveState, StudentDriveOut

Status = Literal["interested", "applied", "test", "interview", "offer", "rejected", "withdrawn"]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2_000)]


class ApplicationIn(BaseModel):
    """PUT /drives/{id}/application. Omit `notes` to keep them; send null to clear."""

    model_config = ConfigDict(extra="forbid")

    status: Status
    notes: Notes | None = None


class EventOut(BaseModel):
    from_status: Status | None  # null = tracking started
    to_status: Status
    at: datetime


class ApplicationOut(BaseModel):
    id: uuid.UUID
    drive_id: uuid.UUID
    status: Status
    notes: str | None
    updated_at: datetime
    timeline: list[EventOut]
    # Moves the server will accept from `status` (state_machine.next_statuses). The
    # frontend draws one button per entry instead of keeping its own copy of the rules.
    next_statuses: list[Status]


class StudentDriveDetailOut(StudentDriveOut):
    """GET /drives/{id}: the drive, the notice, and this student's tracker for it."""

    raw_text: str  # the original notice, only on the detail page (it can be long)
    application: ApplicationOut | None  # null = not tracking this drive yet
    next_statuses: list[Status]  # the starts when not tracking, else application's moves


class TrackedDriveOut(BaseModel):
    id: uuid.UUID
    company: str
    role_title: str
    deadline: datetime
    state: DriveState  # expired / closed drives stay in the tracker history


class TrackerEntryOut(ApplicationOut):
    drive: TrackedDriveOut
