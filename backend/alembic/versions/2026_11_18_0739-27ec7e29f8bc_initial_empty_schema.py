"""initial empty schema

Revision ID: 27ec7e29f8bc
Revises:
Create Date: 2026-11-18 07:39:21.552870

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "27ec7e29f8bc"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
