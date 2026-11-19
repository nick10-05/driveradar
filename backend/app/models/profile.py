"""Student profile: the fields eligibility depends on (DESIGN §5 F1, §6).

Interview notes:
- One row per student, keyed by user_id (a 1:1 table), created when the student first
  saves their profile. Until then the feed stays locked.
- CGPA is NUMERIC(4,2), not float: 7.5 must compare exactly with a drive's 7.5 cutoff.
  Floats can't represent many decimals exactly, which matters at a cutoff boundary.
- Range checks live in the DB too, so bad data can't get in even through a buggy path.
- The Telegram columns are here now (used on Day 8), so that day doesn't need a migration
  that rewrites this table.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StudentProfile(Base):
    __tablename__ = "student_profiles"
    __table_args__ = (
        CheckConstraint("cgpa BETWEEN 0 AND 10", name="cgpa_range"),
        CheckConstraint("active_backlogs >= 0", name="active_backlogs_non_negative"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    branch_code: Mapped[str] = mapped_column(ForeignKey("branches.code"))
    cgpa: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    active_backlogs: Mapped[int] = mapped_column(default=0, server_default="0")
    grad_year: Mapped[int]
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    telegram_link_token_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    telegram_link_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
