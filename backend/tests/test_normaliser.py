"""The normaliser + evidence check: pure functions over the LLM's answer (DESIGN §4.5)."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.services.extraction.evidence import quote_in_text
from app.services.extraction.normaliser import normalise
from app.services.extraction.schema import DraftDrive, ExtractedNotice, FieldIssue

NOW = datetime(2026, 11, 19, 6, 0, tzinfo=UTC)
BRANCHES = {"cse": "CSE", "computer science": "CSE", "it": "IT", "ece": "ECE"}

NOTICE = """Acme Corp is hiring Software Engineers (2027 batch).
CTC: 12 LPA + joining bonus. Location: Bengaluru.
Eligibility: CSE, IT, ECE with CGPA 7.5 and above, no active backlogs.
Apply at https://careers.acme.example/apply by 5 Dec 2026, 5 PM."""

GOOD: dict[str, Any] = {
    "company": "Acme Corp",
    "role_title": "Software Engineer",
    "ctc_text": "12 LPA + joining bonus",
    "ctc_lpa": 12,
    "location": "Bengaluru",
    "apply_link": "https://careers.acme.example/apply",
    "deadline_text": "5 Dec 2026, 5 PM",
    "deadline_local": "2026-12-05T17:00:00",
    "min_cgpa": 7.5,
    "branches_raw": ["CSE", "IT", "ECE"],
    "max_active_backlogs": 0,
    "grad_years": [2027],
    "evidence": {
        "company": "Acme Corp is hiring",
        "deadline": "by 5 Dec 2026, 5 PM",
        "ctc": "CTC: 12 LPA",
        "min_cgpa": "CGPA 7.5 and above",
        "branches": "CSE, IT, ECE",
        "max_active_backlogs": "no active backlogs",
        "grad_years": "(2027 batch)",
    },
}


def run(
    raw: str = NOTICE, rejected: tuple[str, ...] = (), **changes: Any
) -> tuple[DraftDrive, list[FieldIssue]]:
    notice = ExtractedNotice.model_validate(GOOD | changes)
    return normalise(notice, raw, branch_lookup=BRANCHES, now=NOW, rejected_fields=rejected)


def issues_for(issues: list[FieldIssue], field: str) -> list[str]:
    return [issue.kind for issue in issues if issue.field == field]


# ---------------------------------------------------------------- happy path


def test_a_fully_supported_notice_gives_a_clean_draft() -> None:
    draft, issues = run()

    assert issues == []
    assert draft.company == "Acme Corp"
    assert draft.ctc_lpa == Decimal("12.00")
    assert draft.apply_link == "https://careers.acme.example/apply"
    assert draft.deadline == datetime(2026, 12, 5, 11, 30, tzinfo=UTC)  # 17:00 IST
    assert draft.eligibility.min_cgpa == Decimal("7.50")
    assert draft.eligibility.allowed_branches == ["CSE", "ECE", "IT"]
    assert draft.eligibility.max_active_backlogs == 0
    assert draft.eligibility.grad_years == [2027]


# ---------------------------------------------------------------- evidence check


def test_quote_matching_ignores_case_and_whitespace() -> None:
    assert quote_in_text("cgpa   7.5\nand ABOVE", NOTICE)
    assert not quote_in_text("CGPA 8.0 and above", NOTICE)
    assert not quote_in_text("   ", NOTICE)  # an empty quote supports nothing


def test_a_value_without_a_quote_is_flagged_verify_but_kept() -> None:
    evidence = {k: v for k, v in GOOD["evidence"].items() if k != "min_cgpa"}

    draft, issues = run(evidence=evidence)

    assert draft.eligibility.min_cgpa == Decimal("7.50")
    assert issues_for(issues, "eligibility.min_cgpa") == ["verify"]


def test_a_quote_not_found_in_the_notice_is_flagged() -> None:
    # The classic hallucination: a confident value with a made-up "quote".
    draft, issues = run(
        company="Globex", evidence=GOOD["evidence"] | {"company": "Globex is hiring"}
    )

    assert draft.company == "Globex"
    assert issues_for(issues, "company") == ["verify"]


def test_a_real_quote_that_does_not_contain_the_number_is_flagged() -> None:
    # The quote exists in the notice, but the model changed the value.
    _, issues = run(min_cgpa=8.0)

    assert issues_for(issues, "eligibility.min_cgpa") == ["verify"]


def test_grad_year_must_appear_in_its_quote() -> None:
    _, issues = run(grad_years=[2026, 2027])

    assert issues_for(issues, "eligibility.grad_years") == ["verify"]


def test_null_fields_need_no_evidence() -> None:
    _, issues = run(ctc_text=None, ctc_lpa=None, evidence={})

    assert issues_for(issues, "ctc_lpa") == []
    assert issues_for(issues, "ctc_text") == []
    assert issues_for(issues, "company") == ["verify"]  # still non-null, still checked


# ---------------------------------------------------------------- deadline


def test_deadline_with_offset_is_converted_to_utc() -> None:
    draft, _ = run(deadline_local="2026-12-05T17:00:00+00:00")

    assert draft.deadline == datetime(2026, 12, 5, 17, 0, tzinfo=UTC)


def test_date_only_deadline_means_end_of_day_ist_and_is_flagged() -> None:
    draft, issues = run(deadline_local="2026-12-05")

    assert draft.deadline == datetime(2026, 12, 5, 18, 29, tzinfo=UTC)  # 23:59 IST
    assert issues_for(issues, "deadline") == ["verify"]


@pytest.mark.parametrize("value", ["5th December", "2026-13-45T10:00:00", "soon"])
def test_unparseable_deadline_is_nulled_and_flagged(value: str) -> None:
    draft, issues = run(deadline_local=value)

    assert draft.deadline is None
    assert issues_for(issues, "deadline") == ["invalid"]


@pytest.mark.parametrize(
    "value",
    ["2026-11-01T17:00:00", "2028-01-10T17:00:00"],  # past; > 1 year ahead
)
def test_suspicious_deadlines_are_kept_but_flagged(value: str) -> None:
    draft, issues = run(deadline_local=value)

    assert draft.deadline is not None
    assert "verify" in issues_for(issues, "deadline")


def test_missing_deadline_is_flagged_missing() -> None:
    draft, issues = run(deadline_local=None, deadline_text=None)

    assert draft.deadline is None
    assert issues_for(issues, "deadline") == ["missing"]


# ---------------------------------------------------------------- branches


def test_branch_aliases_map_to_codes_ignoring_case_dots_and_spaces() -> None:
    draft, issues = run(
        branches_raw=["Computer  Science", "I.T.", " ece "],
        evidence=GOOD["evidence"] | {"branches": "CSE, IT, ECE"},
    )

    assert draft.eligibility.allowed_branches == ["CSE", "ECE", "IT"]
    assert issues_for(issues, "eligibility.allowed_branches") == []


def test_unknown_branch_is_flagged_by_name_never_silently_dropped() -> None:
    draft, issues = run(branches_raw=["CSE", "Mechatronics"])

    assert draft.eligibility.allowed_branches == ["CSE"]
    flagged = [i for i in issues if i.field == "eligibility.allowed_branches"]
    assert [i.kind for i in flagged] == ["invalid"]
    assert "Mechatronics" in flagged[0].message


def test_all_branches_unknown_is_flagged_because_empty_would_mean_everyone() -> None:
    draft, issues = run(branches_raw=["Mechatronics"])

    assert draft.eligibility.allowed_branches == []
    flagged = [i for i in issues if i.field == "eligibility.allowed_branches"]
    assert "open to ALL branches" in flagged[0].message


@pytest.mark.parametrize("value", [["All branches"], ["any branch"], ["ALL"]])
def test_all_branches_means_no_restriction(value: list[str]) -> None:
    draft, issues = run(branches_raw=value, evidence=GOOD["evidence"] | {"branches": "CSE"})

    assert draft.eligibility.allowed_branches == []
    assert issues_for(issues, "eligibility.allowed_branches") == []


# ---------------------------------------------------------------- sanity checks


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"min_cgpa": 75}, "eligibility.min_cgpa"),  # a percentage, not a 10-point CGPA
        ({"min_cgpa": -1}, "eligibility.min_cgpa"),
        ({"max_active_backlogs": -2}, "eligibility.max_active_backlogs"),
        ({"max_active_backlogs": 500}, "eligibility.max_active_backlogs"),
        ({"ctc_lpa": 1200000}, "ctc_lpa"),  # rupees, not lakhs
        ({"ctc_lpa": 0}, "ctc_lpa"),
        ({"apply_link": "javascript:alert(1)"}, "apply_link"),
        ({"apply_link": "careers page"}, "apply_link"),
        ({"company": "x" * 201}, "company"),
    ],
)
def test_implausible_values_are_nulled_and_flagged_invalid(
    changes: dict[str, Any], field: str
) -> None:
    draft, issues = run(**changes)

    assert issues_for(issues, field) == ["invalid"]
    data = draft.model_dump()
    section, _, name = field.rpartition(".")
    value = data[section][name] if section else data[name]
    assert value is None


def test_cgpa_as_percentage_message_says_so() -> None:
    _, issues = run(min_cgpa=75)

    assert "percentage" in next(i.message for i in issues if i.field == "eligibility.min_cgpa")


def test_out_of_range_grad_years_are_dropped_individually() -> None:
    draft, issues = run(
        grad_years=[2027, 1998], evidence=GOOD["evidence"] | {"grad_years": "2027 batch"}
    )

    assert draft.eligibility.grad_years == [2027]
    assert issues_for(issues, "eligibility.grad_years") == ["invalid"]


def test_a_bad_field_never_blocks_the_rest_of_the_draft() -> None:
    draft, _ = run(min_cgpa=99, deadline_local="garbage", apply_link="nope")

    assert draft.company == "Acme Corp"
    assert draft.eligibility.allowed_branches == ["CSE", "ECE", "IT"]


def test_blank_strings_become_null_quietly() -> None:
    draft, issues = run(location="   ", ctc_text="")

    assert draft.location is None
    assert draft.ctc_text is None
    assert issues_for(issues, "location") == []


def test_missing_company_and_role_are_flagged() -> None:
    _, issues = run(company=None, role_title=None, evidence={})

    assert issues_for(issues, "company") == ["missing"]
    assert issues_for(issues, "role_title") == ["missing"]


# ---------------------------------------------------------------- rejected by Pydantic


def test_fields_the_model_returned_with_a_wrong_type_are_flagged() -> None:
    # The extractor already dropped these (set to null) because their type was wrong.
    _, issues = run(rejected=("min_cgpa", "branches_raw"), min_cgpa=None, branches_raw=None)

    assert issues_for(issues, "eligibility.min_cgpa") == ["invalid"]
    assert issues_for(issues, "eligibility.allowed_branches") == ["invalid"]
