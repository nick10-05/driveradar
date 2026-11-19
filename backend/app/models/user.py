"""Users and their login sessions (DESIGN §6, §7.3).

Interview notes:
- `sessions` stores only the SHA-256 hash of the cookie token. A DB leak alone can't be
  used to log in, because the token itself is never stored.
- `ON DELETE CASCADE` on sessions: deleting a user removes their sessions in the DB, so
  no orphaned logins can survive in any code path.
- Email is stored lower-cased, and a CHECK constraint enforces it, so "A@x.com" and
  "a@x.com" can never become two accounts, even if some code path forgets to normalise.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('student', 'admin')", name="role"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, default="student")
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSession(Base):
    """A login session. Named UserSession so it isn't confused with a SQLAlchemy Session."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Indexed for the Day 9 cleanup job (DELETE ... WHERE expires_at < now()).
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
