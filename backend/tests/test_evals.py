"""The eval harness itself: scoring rules, golden-file loading, and a full run with fakes.

No DB and no network: the branch lookup is a dict and the extractor is a FakeExtractor.
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.extraction.extractors import ManualExtractor
from app.services.extraction.schema import (
    DraftDrive,
    DraftEligibility,
    ExtractedNotice,
    ExtractionResult,
)
from evals.metrics import FIELDS, CaseRun, FieldResult, outcome, score_case, summarise
from evals.run import (
    GoldenFileError,
    as_of_now,
    evaluate,
    load_cases,
    render,
    result_path,
)
from tests.fakes import FakeExtractor

pytestmark = pytest.mark.anyio

LOOKUP = {code.casefold(): code for code in ("CSE", "IT", "ECE", "EEE", "ME", "CE")} | {
    "computer science": "CSE"
}
DEADLINE = datetime(2026, 11, 25, 18, 29, tzinfo=UTC)


# ---------------------------------------------------------------- outcome rules


@pytest.mark.parametrize(
    ("name", "expected", "actual", "result"),
    [
        ("company", "Northwind", "  northwind ", "correct"),
        ("company", "Northwind", "Southwind", "wrong"),
        ("company", "Northwind", None, "missed"),
        ("company", None, None, "abstained"),
        ("company", None, "Northwind", "hallucinated"),
        ("company", None, "   ", "abstained"),  # blank text = nothing extracted
        ("min_cgpa", 7.5, Decimal("7.50"), "correct"),  # float vs Decimal: no noise
        ("ctc_lpa", 6, Decimal("6.00"), "correct"),
        ("ctc_lpa", 6, Decimal("8.00"), "wrong"),
        ("max_active_backlogs", 0, 0, "correct"),  # 0 is a value, not "unstated"
        ("max_active_backlogs", None, 0, "hallucinated"),
        ("deadline", "2026-11-25T18:29:00Z", DEADLINE, "correct"),
        ("deadline", "2026-11-25T18:29:00Z", DEADLINE.replace(second=1), "wrong"),
        ("grad_years", [2028, 2027], [2027, 2028], "correct"),  # order doesn't matter
        ("grad_years", [], [], "abstained"),
        ("allowed_branches", ["CSE", "IT"], ["IT", "CSE"], "correct"),
        ("allowed_branches", ["CSE", "IT"], ["CSE"], "wrong"),
        ("allowed_branches", [], ["CSE"], "hallucinated"),  # notice said all branches
    ],
)
def test_outcome(name: str, expected: object, actual: object, result: str) -> None:
    assert outcome(name, expected, actual) == result


def test_score_case_covers_every_field_once() -> None:
    results = score_case({name: None for name in FIELDS}, DraftDrive())
    assert [r.field for r in results] == list(FIELDS)
    assert {r.outcome for r in results} == {"abstained"}


# ---------------------------------------------------------------- summary


def _run(case_id: str, fields: list[FieldResult], status: str = "ok", **kw: int) -> CaseRun:
    return CaseRun(case_id=case_id, status=status, latency_ms=100, fields=fields, **kw)


def test_summary_rates_and_branch_precision_recall() -> None:
    runs = [
        _run(
            "a",
            [
                FieldResult("company", "correct", "X", "X"),
                FieldResult("location", "hallucinated", None, "Pune"),
                FieldResult("allowed_branches", "wrong", ["CSE", "IT"], ["CSE", "ECE"]),
            ],
            evidence_checked=4,
            evidence_passed=3,
        ),
        _run(
            "b",
            [
                FieldResult("company", "missed", "Y", None),
                FieldResult("location", "abstained", None, None),
            ],
            status="invalid",
        ),
    ]
    s = summarise(runs)
    assert s.cases == 2
    assert s.stated_accuracy == pytest.approx(1 / 3)  # 1 correct of correct+missed+wrong
    assert s.hallucination_rate == pytest.approx(1 / 2)
    assert s.branch_precision == pytest.approx(1 / 2)  # CSE right, ECE wrong
    assert s.branch_recall == pytest.approx(1 / 2)  # CSE found, IT missed
    assert s.evidence_pass_rate == pytest.approx(3 / 4)
    assert s.invalid_rate == pytest.approx(1 / 2)
    assert s.mean_latency_ms == 100


def test_summary_of_nothing_is_not_measured_rather_than_zero() -> None:
    s = summarise([])
    assert s.stated_accuracy is None
    assert s.branch_precision is None
    assert s.invalid_rate is None
    assert s.mean_latency_ms is None


# ---------------------------------------------------------------- golden files


def test_golden_set_loads_and_is_all_labelled_synthetic() -> None:
    cases = load_cases()
    assert len(cases) >= 6
    assert len({c.id for c in cases}) == len(cases)
    assert all(c.synthetic for c in cases if c.id.startswith("synthetic"))
    for case in cases:  # every label is in a form the scorer understands
        for result in score_case(case.expected, DraftDrive()):
            assert result.outcome in ("missed", "abstained")


def test_golden_file_missing_a_field_is_rejected(tmp_path: Path) -> None:
    bad = {"id": "x", "synthetic": True, "as_of": "2026-11-19", "raw_text": "t"}
    (tmp_path / "bad.json").write_text(json.dumps(bad | {"expected": {"company": "X"}}))
    with pytest.raises(GoldenFileError, match="missing"):
        load_cases(tmp_path)


# ---------------------------------------------------------------- full runs with fakes

PERFECT_01 = ExtractedNotice(
    company="Northwind Systems",
    role_title="Graduate Engineer Trainee",
    ctc_text="4.5 LPA",
    ctc_lpa=4.5,
    location="Pune",
    apply_link="https://careers.northwind.example/apply",
    deadline_text="25 November 2026, 11:59 PM",
    deadline_local="2026-11-25T23:59:00",
    min_cgpa=6.5,
    branches_raw=["CSE", "IT", "ECE", "EEE"],
    max_active_backlogs=0,
    grad_years=[2027],
    evidence={
        "company": "Northwind Systems is visiting",
        "deadline": "25 November 2026, 11:59 PM",
        "ctc": "CTC: 4.5 LPA",
        "min_cgpa": "CGPA 6.5 and above",
        "branches": "Branches: CSE, IT, ECE, EEE",
        "max_active_backlogs": "No active backlogs",
        "grad_years": "2027 passing out batch only",
    },
)


async def test_perfect_extraction_scores_every_field_right() -> None:
    case = next(c for c in load_cases() if c.id == "synthetic-01")
    fake = FakeExtractor(ExtractionResult(status="ok", notice=PERFECT_01, model="fake"))
    [run] = await evaluate([case], lambda _day: fake, LOOKUP)

    assert run.status == "ok"
    assert {r.field: r.outcome for r in run.fields if r.outcome != "correct"} == {}
    assert (run.evidence_checked, run.evidence_passed) == (7, 7)
    assert fake.calls == [case.raw_text]


async def test_hallucinated_evidence_is_counted() -> None:
    case = next(c for c in load_cases() if c.id == "synthetic-01")
    notice = PERFECT_01.model_copy(
        update={"evidence": {**PERFECT_01.evidence, "min_cgpa": "CGPA 8.0 and above"}}
    )
    fake = FakeExtractor(ExtractionResult(status="ok", notice=notice))
    [run] = await evaluate([case], lambda _day: fake, LOOKUP)
    assert (run.evidence_checked, run.evidence_passed) == (7, 6)


async def test_manual_baseline_misses_everything_and_invents_nothing() -> None:
    cases = load_cases()
    runs = await evaluate(cases, lambda _day: ManualExtractor(), LOOKUP)
    s = summarise(runs)
    assert s.statuses["disabled"] == len(cases)
    assert s.stated_accuracy == 0
    assert s.hallucination_rate == 0
    assert s.evidence_pass_rate is None


async def test_extractor_crash_counts_as_error_not_abort() -> None:
    class Boom:
        async def extract(self, raw_text: str) -> ExtractionResult:
            raise RuntimeError("bug")

    cases = load_cases()[:2]
    runs = await evaluate(cases, lambda _day: Boom(), LOOKUP)
    assert [(r.status, r.error) for r in runs] == [("error", "unexpected")] * 2


async def test_each_case_gets_its_own_as_of_date() -> None:
    cases = load_cases()[:2]
    seen: list[date] = []

    def make(day: date) -> ManualExtractor:
        seen.append(day)
        return ManualExtractor()

    await evaluate(cases, make, LOOKUP)
    assert seen == [c.as_of for c in cases]


def test_as_of_now_is_noon_ist_in_utc() -> None:
    assert as_of_now(date(2026, 11, 19)) == datetime(2026, 11, 19, 6, 30, tzinfo=UTC)


# ---------------------------------------------------------------- report


async def test_report_shows_metrics_errors_and_synthetic_warning() -> None:
    cases = load_cases()
    runs = await evaluate(cases, lambda _day: ManualExtractor(), LOOKUP)
    report = render(
        summarise(runs), runs, cases, provider="none", model=None, run_date=date(2026, 11, 19)
    )
    assert report.startswith("# Eval: none / - / prompt v1")
    assert "| Stated fields extracted exactly | 0% |" in report
    assert "| Evidence quotes found in notice | n/a (0/0) |" in report
    assert "`synthetic-01` company: missed" in report
    assert "not real notices" in report


def test_report_without_errors_says_none() -> None:
    draft = DraftDrive(company="X", eligibility=DraftEligibility())
    expected = {name: None for name in FIELDS} | {"company": "X"}
    run = _run("x", score_case(expected, draft))
    report = render(summarise([run]), [run], [], provider="p", model="m", run_date=date.today())
    assert "## Errors\n\nNone." in report


def test_result_path_is_filesystem_safe() -> None:
    path = result_path("openai_compatible", "org/model:7b", date(2026, 11, 19))
    assert path.name == "2026-11-19-openai_compatible-org-model-7b-v1.md"
