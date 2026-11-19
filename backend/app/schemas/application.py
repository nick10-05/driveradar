"""Tracker request/response models (DESIGN §5 F4, §8)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.drive import DriveState

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


class TrackedDriveOut(BaseModel):
    id: uuid.UUID
    company: str
    role_title: str
    deadline: datetime
    state: DriveState  # expired / closed drives stay in the tracker history


class TrackerEntryOut(ApplicationOut):
    drive: TrackedDriveOut
