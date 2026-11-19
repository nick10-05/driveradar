"""seed placeholder branches

PLACEHOLDER data until the college's real branch codes are confirmed (DESIGN §13 Q2).
Real codes will come in a new migration; this one stays as history.

Interview notes:
- Lookup data the app needs to work goes in a migration, so every environment (local, CI,
  prod) gets the same rows in the same order as the schema, with no manual step.
- The migration uses lightweight `sa.table()` definitions, not the ORM models: models
  change later, but this migration must keep working exactly as written.

Revision ID: 20858207eeb9
Revises: 04cf2fae49d7
Create Date: 2026-11-18 20:25:35.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20858207eeb9"
down_revision: str | Sequence[str] | None = "04cf2fae49d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

branches = sa.table("branches", sa.column("code", sa.Text), sa.column("name", sa.Text))
branch_aliases = sa.table(
    "branch_aliases", sa.column("alias", sa.Text), sa.column("branch_code", sa.Text)
)

# code -> (name, aliases). Aliases are lower-cased.
BRANCHES: dict[str, tuple[str, list[str]]] = {
    "CSE": (
        "Computer Science and Engineering",
        ["cse", "cs", "computer science", "computer science and engineering"],
    ),
    "IT": ("Information Technology", ["it", "information technology"]),
    "ECE": (
        "Electronics and Communication Engineering",
        ["ece", "ec", "electronics and communication", "electronics and communication engineering"],
    ),
    "EEE": (
        "Electrical and Electronics Engineering",
        ["eee", "electrical and electronics", "electrical and electronics engineering"],
    ),
    "ME": ("Mechanical Engineering", ["me", "mech", "mechanical", "mechanical engineering"]),
    "CE": ("Civil Engineering", ["ce", "civil", "civil engineering"]),
}


def upgrade() -> None:
    op.bulk_insert(branches, [{"code": code, "name": name} for code, (name, _) in BRANCHES.items()])
    op.bulk_insert(
        branch_aliases,
        [
            {"alias": alias, "branch_code": code}
            for code, (_, aliases) in BRANCHES.items()
            for alias in aliases
        ],
    )


def downgrade() -> None:
    codes = list(BRANCHES)
    op.execute(branch_aliases.delete().where(branch_aliases.c.branch_code.in_(codes)))
    op.execute(branches.delete().where(branches.c.code.in_(codes)))
