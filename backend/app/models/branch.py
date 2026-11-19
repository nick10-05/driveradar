"""Branch lookup tables (DESIGN §6).

Interview notes:
- Branches are codes in a table, not free text. Profiles and drive rules reference them by
  foreign key, so a typo like "CSE " or a deleted branch can't sneak in.
- Aliases map the many ways notices write a branch ("cs", "computer science") to one code.
  The Day 4 normaliser uses them; the LLM never decides the mapping.
"""

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Branch(Base):
    __tablename__ = "branches"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class BranchAlias(Base):
    __tablename__ = "branch_aliases"

    alias: Mapped[str] = mapped_column(Text, primary_key=True)  # stored lower-cased
    branch_code: Mapped[str] = mapped_column(ForeignKey("branches.code"))
