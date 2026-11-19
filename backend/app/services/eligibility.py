"""The eligibility check (DESIGN §5 F3, D9).

Interview notes:
- A pure function: plain values in, a result out. No DB, no HTTP, no clock, no LLM. That
  makes it trivially unit-testable (including exact boundary values) and it gives the
  same answer every time, which is the point of the "deterministic boundary" in D9.
- It returns reasons, not just a bool. The feed shows ineligible drives greyed out with
  "Needs CGPA ≥ 7.5 (you: 7.2)", so nothing is hidden silently and a wrong rule is easy
  to spot and report.
- Every rule is checked (no early return), so a student sees all the reasons at once.
- An empty rule means "no restriction": None for the numbers, an empty set for branches
  and years.
- Decimal, not float: 7.5 vs 7.50 must compare exactly at the cutoff.
- The inputs are small dataclasses, not ORM models, so this module doesn't depend on the
  database layer at all. The caller converts (see services/drives.py).
"""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class StudentFacts:
    branch_code: str
    cgpa: Decimal
    active_backlogs: int
    grad_year: int


@dataclass(frozen=True, slots=True)
class EligibilityRules:
    min_cgpa: Decimal | None = None
    max_active_backlogs: int | None = None
    grad_years: frozenset[int] = frozenset()
    allowed_branches: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    eligible: bool
    reasons: list[str] = field(default_factory=list)


def check_eligibility(student: StudentFacts, rules: EligibilityRules) -> EligibilityResult:
    reasons: list[str] = []

    if rules.allowed_branches and student.branch_code not in rules.allowed_branches:
        branches = ", ".join(sorted(rules.allowed_branches))
        reasons.append(f"Open to {branches} only (you: {student.branch_code})")

    if rules.min_cgpa is not None and student.cgpa < rules.min_cgpa:
        reasons.append(f"Needs CGPA ≥ {_plain(rules.min_cgpa)} (you: {_plain(student.cgpa)})")

    if rules.max_active_backlogs is not None and (
        student.active_backlogs > rules.max_active_backlogs
    ):
        if rules.max_active_backlogs == 0:
            limit = "Needs no active backlogs"
        else:
            limit = f"Allows at most {rules.max_active_backlogs} active backlogs"
        reasons.append(f"{limit} (you: {student.active_backlogs})")

    if rules.grad_years and student.grad_year not in rules.grad_years:
        years = ", ".join(str(year) for year in sorted(rules.grad_years))
        batch = "batch" if len(rules.grad_years) == 1 else "batches"
        reasons.append(f"For the {years} {batch} only (you: {student.grad_year})")

    return EligibilityResult(eligible=not reasons, reasons=reasons)


def _plain(value: Decimal) -> str:
    """7.50 -> "7.5", 10.00 -> "10" (normalize() alone would give "1E+1")."""
    return f"{value.normalize():f}"
