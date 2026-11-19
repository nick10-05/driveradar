"""Scoring: compare the pipeline's draft with the hand-labelled answer (DESIGN §4.9).

Pure functions, no I/O, so the scoring rules are unit-tested like any other code.

Interview notes:
- Each field of each notice gets exactly one outcome. The point is to separate the two
  ways an extractor can be wrong:
    stated in the notice   → correct | missed (left empty) | wrong (different value)
    unstated in the notice → abstained (left empty, good) | hallucinated (invented)
  "Missed" costs the admin a few seconds of typing. "Hallucinated" and "wrong" are the
  dangerous ones: a confident value that isn't true. So they are reported separately
  instead of folded into one accuracy number.
- Branches also get precision/recall over codes, because a list can be partly right:
  precision = "of the codes it gave, how many were right" (low = it listed
  branches the notice never named); recall = "of the right codes, how many it found".
- Text is compared after case-folding and collapsing whitespace. Anything looser (fuzzy
  matching) would hide real errors; the admin review catches cosmetic differences anyway.
"""

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from app.services.extraction.schema import DraftDrive

Outcome = Literal["correct", "missed", "wrong", "abstained", "hallucinated"]
OUTCOMES: tuple[Outcome, ...] = ("correct", "missed", "wrong", "abstained", "hallucinated")

TEXT_FIELDS = ("company", "role_title", "location", "apply_link")
NUMBER_FIELDS = ("ctc_lpa", "min_cgpa", "max_active_backlogs")
LIST_FIELDS = ("grad_years", "allowed_branches")
FIELDS = (*TEXT_FIELDS, *NUMBER_FIELDS, "deadline", *LIST_FIELDS)

_SPACES = re.compile(r"\s+")


def draft_values(draft: DraftDrive) -> dict[str, Any]:
    """The draft flattened to the golden file's field names."""
    rules = draft.eligibility
    return {
        "company": draft.company,
        "role_title": draft.role_title,
        "location": draft.location,
        "apply_link": draft.apply_link,
        "ctc_lpa": draft.ctc_lpa,
        "deadline": draft.deadline,
        "min_cgpa": rules.min_cgpa,
        "max_active_backlogs": rules.max_active_backlogs,
        "grad_years": rules.grad_years,
        "allowed_branches": rules.allowed_branches,
    }


def _canonical(name: str, value: Any) -> Any:
    """Bring expected and actual values to one comparable form. None = not stated."""
    if value is None:
        return None
    if name in TEXT_FIELDS:
        text = _SPACES.sub(" ", str(value)).strip().casefold()
        return text or None
    if name in NUMBER_FIELDS:
        return Decimal(str(value))  # via str: 7.5 == Decimal("7.50"), no float noise
    if name == "deadline":
        return value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if name in LIST_FIELDS:
        items = frozenset(str(v).upper() if name == "allowed_branches" else int(v) for v in value)
        return items or None  # [] = "not stated" / "all branches"
    raise KeyError(name)


def outcome(name: str, expected: Any, actual: Any) -> Outcome:
    want, got = _canonical(name, expected), _canonical(name, actual)
    if want is None:
        return "abstained" if got is None else "hallucinated"
    if got is None:
        return "missed"
    return "correct" if want == got else "wrong"


@dataclass(frozen=True, slots=True)
class FieldResult:
    field: str
    outcome: Outcome
    expected: Any
    actual: Any


def score_case(expected: Mapping[str, Any], draft: DraftDrive) -> list[FieldResult]:
    actual = draft_values(draft)
    results = []
    for name in FIELDS:
        want, got = expected.get(name), actual[name]
        results.append(FieldResult(name, outcome(name, want, got), want, got))
    return results


@dataclass(frozen=True, slots=True)
class CaseRun:
    """One notice through the pipeline, as the report needs it."""

    case_id: str
    status: str  # extractor status: ok | invalid | error | disabled
    latency_ms: int
    fields: list[FieldResult]
    evidence_checked: int = 0  # evidence quotes the model gave
    evidence_passed: int = 0  # ... that really appear in the notice
    error: str | None = None


@dataclass(slots=True)
class Summary:
    cases: int = 0
    statuses: Counter[str] = field(default_factory=Counter)
    per_field: dict[str, Counter[str]] = field(default_factory=dict)
    branch_tp: int = 0
    branch_fp: int = 0
    branch_fn: int = 0
    evidence_checked: int = 0
    evidence_passed: int = 0
    total_latency_ms: int = 0

    @property
    def totals(self) -> Counter[str]:
        total: Counter[str] = Counter()
        for counts in self.per_field.values():
            total.update(counts)
        return total

    @property
    def stated_accuracy(self) -> float | None:
        """Of the fields the notices state, the share extracted exactly right."""
        t = self.totals
        return _ratio(t["correct"], t["correct"] + t["missed"] + t["wrong"])

    @property
    def hallucination_rate(self) -> float | None:
        """Of the fields the notices don't state, the share the pipeline invented anyway."""
        t = self.totals
        return _ratio(t["hallucinated"], t["hallucinated"] + t["abstained"])

    @property
    def branch_precision(self) -> float | None:
        return _ratio(self.branch_tp, self.branch_tp + self.branch_fp)

    @property
    def branch_recall(self) -> float | None:
        return _ratio(self.branch_tp, self.branch_tp + self.branch_fn)

    @property
    def evidence_pass_rate(self) -> float | None:
        return _ratio(self.evidence_passed, self.evidence_checked)

    @property
    def invalid_rate(self) -> float | None:
        """Calls that reached the model but returned unusable output."""
        return _ratio(self.statuses["invalid"], self.cases)

    @property
    def mean_latency_ms(self) -> float | None:
        return self.total_latency_ms / self.cases if self.cases else None


def _ratio(part: int, whole: int) -> float | None:
    return part / whole if whole else None  # None = "nothing to measure", not 0%


def summarise(runs: Iterable[CaseRun]) -> Summary:
    summary = Summary(per_field={name: Counter() for name in FIELDS})
    for run in runs:
        summary.cases += 1
        summary.statuses[run.status] += 1
        summary.total_latency_ms += run.latency_ms
        summary.evidence_checked += run.evidence_checked
        summary.evidence_passed += run.evidence_passed
        for result in run.fields:
            summary.per_field[result.field][result.outcome] += 1
            if result.field == "allowed_branches":
                want = _canonical("allowed_branches", result.expected) or frozenset()
                got = _canonical("allowed_branches", result.actual) or frozenset()
                summary.branch_tp += len(want & got)
                summary.branch_fp += len(got - want)
                summary.branch_fn += len(want - got)
    return summary
