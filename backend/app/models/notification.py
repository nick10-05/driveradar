"""Sent Telegram alerts (DESIGN §5 F5, §6).

Interview notes:
- UNIQUE(student, drive, kind) is the duplicate guard: insert the row first and send only
  if the insert went in. Publishing twice, a retried cron run, or two workers racing can
  never send the same alert twice; the database decides, not application timing.
- A row means "sent". If sending fails for a temporary reason the row is deleted again,
  so a later run may retry it.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

NOTIFICATION_KINDS = ("new_drive", "deadline_24h", "deadline_3h")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("student_id", "drive_id", "kind"),
        CheckConstraint(
            "kind IN (" + ", ".join(f"'{kind}'" for kind in NOTIFICATION_KINDS) + ")",
            name="kind_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    drive_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drives.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
