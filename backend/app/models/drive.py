"""Placement drives and their eligibility rules (DESIGN §5 F2/F3, §6).

Interview notes:
- Stored status is only draft → published → closed. "Expired" is NOT a status: it is
  computed as `published AND deadline <= now()`. Nothing has to flip a flag at the
  deadline (no job that can fail or run late), and extending a deadline reopens the
  drive automatically.
- `closed` is set only by an admin (cancelled, filled, withdrawn); closed_at records when.
- The deadline is timestamptz: stored in UTC, shown in IST by the frontend.
- CTC is kept twice: the notice's own text ("12 LPA + 2L joining bonus") and an optional
  number for sorting. Money as NUMERIC, never float.
- Branch rules are a join table with foreign keys to `branches`: a Postgres array can't
  have foreign keys, so a text[] could hold typos or deleted codes. Graduation years stay
  an array because there is nothing for them to reference.
- One `drive_eligibility` row per drive (created with the drive), so loading rules never
  needs an "if the row exists" branch. NULL / empty = no restriction.
- `extraction_run_id` (DESIGN §6) is added on Day 4, together with `extraction_runs`.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

DRIVE_STATUSES = ("draft", "published", "closed")
DRIVE_SOURCES = ("email", "whatsapp", "portal", "telegram", "other")


class Drive(Base):
    __tablename__ = "drives"
    __table_args__ = (
        CheckConstraint(f"status IN {DRIVE_STATUSES}", name="status"),
        CheckConstraint(f"source IN {DRIVE_SOURCES}", name="source"),
        CheckConstraint("ctc_lpa >= 0", name="ctc_lpa_non_negative"),
        # closed_at is set exactly when the drive is closed, never otherwise.
        CheckConstraint("(status = 'closed') = (closed_at IS NOT NULL)", name="closed_at_matches"),
        # The feed query: WHERE status = 'published' AND deadline > now() ORDER BY deadline.
        Index("ix_drives_status_deadline", "status", "deadline"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company: Mapped[str] = mapped_column(Text)
    role_title: Mapped[str] = mapped_column(Text)
    ctc_text: Mapped[str | None] = mapped_column(Text)
    ctc_lpa: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    location: Mapped[str | None] = mapped_column(Text)
    apply_link: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="draft", server_default="draft")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    eligibility: Mapped["DriveEligibility"] = relationship(
        cascade="all, delete-orphan", lazy="raise"
    )
    allowed_branches: Mapped[list["DriveAllowedBranch"]] = relationship(
        cascade="all, delete-orphan", lazy="raise", order_by="DriveAllowedBranch.branch_code"
    )


class DriveEligibility(Base):
    __tablename__ = "drive_eligibility"
    __table_args__ = (
        CheckConstraint("min_cgpa BETWEEN 0 AND 10", name="min_cgpa_range"),
        CheckConstraint("max_active_backlogs >= 0", name="max_active_backlogs_non_negative"),
    )

    drive_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("drives.id", ondelete="CASCADE"), primary_key=True
    )
    min_cgpa: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    max_active_backlogs: Mapped[int | None]
    grad_years: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))


class DriveAllowedBranch(Base):
    """No rows for a drive = open to all branches."""

    __tablename__ = "drive_allowed_branches"

    drive_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("drives.id", ondelete="CASCADE"), primary_key=True
    )
    branch_code: Mapped[str] = mapped_column(ForeignKey("branches.code"), primary_key=True)
