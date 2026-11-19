"""Audit log of every extraction attempt (DESIGN §4.8).

Interview notes:
- Every attempt is stored, failures included: provider, model, prompt version, status,
  the normalised draft, its issues, latency and token counts. That answers "what did the
  AI suggest, with which prompt, and how long did it take?" for any drive.
- A drive saved from a draft links back to its run (drives.extraction_run_id). Comparing
  the run's draft with the published drive gives the per-field admin edit rate: a live
  accuracy metric that needs no extra labelling.
- `error` is a short code ("timeout", "http_429"), never provider content.
- raw_text is stored: the notice is meant for the whole batch, and an audit row is only
  useful if you can see what was read. It is never logged.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

EXTRACTION_STATUSES = ("ok", "invalid", "error", "disabled")


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (CheckConstraint(f"status IN {EXTRACTION_STATUSES}", name="status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    raw_text: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    latency_ms: Mapped[int | None]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
