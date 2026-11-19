"""Normaliser: the LLM's answer → a draft in our own vocabulary + per-field issues.

DESIGN §4.5. Pure: no DB, no network, no clock (`now` and the branch lookup are passed
in), so every rule is a plain unit test.

Interview notes:
- This is the trusted half of the AI boundary (D9). The model proposes; this code
  converts and checks: IST → UTC, branch names → codes via `branch_aliases`, ranges,
  http(s) links, evidence quotes.
- A bad field is set to null and flagged; it never blocks the rest of the draft. The admin
  sees each flag next to the field and fixes it in the same form.
- Flags, not silent fixes. The one place this matters most: if none of the notice's
  branch names can be mapped, the rule list comes out empty, and empty means "all
  branches". That would silently WIDEN the drive, so it gets an explicit warning.
"""

import re
from collections.abc import Collection, Mapping
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from pydantic import HttpUrl, TypeAdapter, ValidationError

from app.schemas.drive import IST
from app.services.extraction.evidence import quote_in_text
from app.services.extraction.schema import (
    DraftDrive,
    DraftEligibility,
    ExtractedNotice,
    FieldIssue,
    IssueKind,
    quantize2,
)

MAX_TEXT = 200  # same limit as DriveCreate
MAX_CTC_LPA = 200  # above this it is almost certainly rupees, not lakhs
END_OF_DAY = time(23, 59)
ALL_BRANCHES = frozenset({"all", "all branches", "any", "any branch", "all streams"})

# ExtractedNotice field → the draft field the review form shows it in.
DRAFT_FIELD = {
    "company": "company",
    "role_title": "role_title",
    "ctc_text": "ctc_text",
    "ctc_lpa": "ctc_lpa",
    "location": "location",
    "apply_link": "apply_link",
    "deadline_text": "deadline",
    "deadline_local": "deadline",
    "min_cgpa": "eligibility.min_cgpa",
    "branches_raw": "eligibility.allowed_branches",
    "max_active_backlogs": "eligibility.max_active_backlogs",
    "grad_years": "eligibility.grad_years",
}
REQUIRED = ("company", "role_title", "deadline")

_HTTP_URL = TypeAdapter(HttpUrl)


class _Issues:
    def __init__(self) -> None:
        self.items: list[FieldIssue] = []

    def add(self, field: str, kind: IssueKind, message: str) -> None:
        self.items.append(FieldIssue(field=field, kind=kind, message=message))

    def has(self, field: str, kind: IssueKind) -> bool:
        return any(i.field == field and i.kind == kind for i in self.items)


def normalise(
    notice: ExtractedNotice,
    raw_text: str,
    *,
    branch_lookup: Mapping[str, str],
    now: datetime,
    rejected_fields: Collection[str] = (),
) -> tuple[DraftDrive, list[FieldIssue]]:
    """branch_lookup: lower-cased alias or code → branch code (from branches + aliases)."""
    issues = _Issues()
    for name in sorted(rejected_fields):
        if name in DRAFT_FIELD:
            issues.add(
                DRAFT_FIELD[name], "invalid", "The AI's value had the wrong type; fill it in."
            )

    draft = DraftDrive(
        company=_text(notice.company, "company", issues),
        role_title=_text(notice.role_title, "role_title", issues),
        ctc_text=_text(notice.ctc_text, "ctc_text", issues),
        ctc_lpa=_ctc(notice.ctc_lpa, issues),
        location=_text(notice.location, "location", issues),
        apply_link=_link(notice.apply_link, issues),
        deadline=_deadline(notice.deadline_local, now, issues),
        eligibility=DraftEligibility(
            min_cgpa=_cgpa(notice.min_cgpa, issues),
            max_active_backlogs=_backlogs(notice.max_active_backlogs, issues),
            grad_years=_grad_years(notice.grad_years, now, issues),
            allowed_branches=_branches(notice.branches_raw, branch_lookup, issues),
        ),
    )
    _check_evidence(notice, draft, raw_text, issues)
    for field in REQUIRED:
        if getattr(draft, field) is None and not issues.has(field, "invalid"):
            issues.add(field, "missing", "Not found in the notice; fill it in.")
    return draft, issues.items


# ---------------------------------------------------------------- per-field rules


def _text(value: str | None, field: str, issues: _Issues) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if len(value) > MAX_TEXT:
        issues.add(field, "invalid", f"Longer than {MAX_TEXT} characters.")
        return None
    return value


def _ctc(value: float | None, issues: _Issues) -> Decimal | None:
    if value is None:
        return None
    if not 0 < value <= MAX_CTC_LPA:
        issues.add("ctc_lpa", "invalid", f"{value} is not a plausible CTC in LPA.")
        return None
    return quantize2(value)


def _link(value: str | None, issues: _Issues) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return str(_HTTP_URL.validate_python(value))
    except ValidationError:
        issues.add("apply_link", "invalid", "Not an http(s) link.")
        return None


def _deadline(value: str | None, now: datetime, issues: _Issues) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        issues.add("deadline", "invalid", f"Couldn't read the date {value!r}.")
        return None
    if "T" not in value and " " not in value:  # a date with no time
        parsed = datetime.combine(parsed.date(), END_OF_DAY)
        issues.add("deadline", "verify", "No time given; assumed 23:59 IST.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)  # Indian notices rarely say "IST"
    deadline = parsed.astimezone(UTC)
    if deadline <= now:
        issues.add("deadline", "verify", "The deadline is in the past.")
    elif deadline > now + timedelta(days=365):
        issues.add("deadline", "verify", "The deadline is more than a year away.")
    return deadline


def _cgpa(value: float | None, issues: _Issues) -> Decimal | None:
    if value is None:
        return None
    if 0 <= value <= 10:
        return quantize2(value)
    hint = " It looks like a percentage." if 10 < value <= 100 else ""
    issues.add("eligibility.min_cgpa", "invalid", f"{value} is not a 10-point CGPA.{hint}")
    return None


def _backlogs(value: int | None, issues: _Issues) -> int | None:
    if value is None:
        return None
    if 0 <= value <= 100:
        return value
    issues.add("eligibility.max_active_backlogs", "invalid", f"{value} is not a backlog limit.")
    return None


def _grad_years(values: list[int] | None, now: datetime, issues: _Issues) -> list[int]:
    lowest, highest = now.year - 2, now.year + 2
    kept = sorted({year for year in values or () if lowest <= year <= highest})
    dropped = sorted({year for year in values or () if not lowest <= year <= highest})
    if dropped:
        issues.add(
            "eligibility.grad_years",
            "invalid",
            f"Ignored {', '.join(map(str, dropped))}: outside {lowest}-{highest}.",
        )
    return kept


def _branch_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace(".", "")).strip().casefold()


def _branches(values: list[str] | None, lookup: Mapping[str, str], issues: _Issues) -> list[str]:
    names = [name for name in values or () if name.strip()]
    if not names or all(_branch_key(name) in ALL_BRANCHES for name in names):
        return []
    codes = {lookup[_branch_key(name)] for name in names if _branch_key(name) in lookup}
    unknown = [name for name in names if _branch_key(name) not in lookup]
    if unknown:
        message = f"Unknown branch names: {', '.join(unknown)}. Pick the codes yourself."
        if not codes:
            message += " Left empty, the drive would be open to ALL branches."
        issues.add("eligibility.allowed_branches", "invalid", message)
    return sorted(codes)


# ---------------------------------------------------------------- evidence


def _plain(value: Decimal) -> str:
    return f"{value.normalize():f}"


def _check_evidence(
    notice: ExtractedNotice, draft: DraftDrive, raw_text: str, issues: _Issues
) -> None:
    rules = draft.eligibility
    ctc_field = "ctc_text" if draft.ctc_text is not None else "ctc_lpa"
    # evidence key → (draft field, value is present, strings that must appear in the quote)
    checks: dict[str, tuple[str, bool, list[str]]] = {
        "company": ("company", draft.company is not None, []),
        "deadline": ("deadline", draft.deadline is not None, []),
        "ctc": (ctc_field, draft.ctc_text is not None or draft.ctc_lpa is not None, []),
        "min_cgpa": (
            "eligibility.min_cgpa",
            rules.min_cgpa is not None,
            [_plain(rules.min_cgpa)] if rules.min_cgpa is not None else [],
        ),
        "branches": ("eligibility.allowed_branches", bool(notice.branches_raw), []),
        "max_active_backlogs": (
            "eligibility.max_active_backlogs",
            rules.max_active_backlogs is not None,
            [],
        ),
        "grad_years": (
            "eligibility.grad_years",
            bool(rules.grad_years),
            [str(year) for year in rules.grad_years],
        ),
    }
    for key, (field, present, must_contain) in checks.items():
        if not present or issues.has(field, "invalid"):
            continue
        quote = notice.evidence.get(key, "")
        if not quote_in_text(quote, raw_text):
            issues.add(field, "verify", "No supporting quote found in the notice; check it.")
        elif any(part not in quote for part in must_contain):
            issues.add(field, "verify", "The quoted text doesn't contain this value; check it.")
