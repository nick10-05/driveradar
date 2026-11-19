"""A student's application tracker: one row per (student, drive) + its event timeline.

DESIGN §5 F4, §6.

Interview notes:
- UNIQUE(student_id, drive_id): a student tracks a drive once. The DB enforces it, so
  two quick clicks can't create two trackers.
- application_events is append-only: each accepted status change adds a row
  (from → to, when). The current status is also stored on `applications` for fast reads;
  the events are the history ("applied on the 3rd, test on the 9th").
- The status CHECK lists the same states as the state machine, so even a buggy code path
  can't store an unknown status.
- ON DELETE CASCADE from users and drives: removing either removes its trackers and
  their events; no orphans.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.services.state_machine import STATUSES

_STATUS_LIST = tuple(sorted(STATUSES))


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("student_id", "drive_id"),
        CheckConstraint(f"status IN {_STATUS_LIST}", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    drive_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drives.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    events: Mapped[list["ApplicationEvent"]] = relationship(
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="ApplicationEvent.at",
    )


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    __table_args__ = (
        CheckConstraint(f"to_status IN {_STATUS_LIST}", name="to_status"),
        CheckConstraint(f"from_status IN {_STATUS_LIST}", name="from_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(Text)  # NULL = tracking started
    to_status: Mapped[str] = mapped_column(Text)
    # clock_timestamp(), not now(): now() is frozen for the whole transaction, so two
    # events written in one transaction would tie and the timeline order would be lost.
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
