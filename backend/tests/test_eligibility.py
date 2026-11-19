"""check_eligibility(): a pure function, so no DB or HTTP needed (DESIGN §5 F3)."""

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from app.services.eligibility import (
    EligibilityResult,
    EligibilityRules,
    StudentFacts,
    check_eligibility,
)

STUDENT = StudentFacts(branch_code="CSE", cgpa=Decimal("7.50"), active_backlogs=0, grad_year=2027)
NO_RULES = EligibilityRules()


def student(**changes: Any) -> StudentFacts:
    return replace(STUDENT, **changes)


def test_no_rules_means_everyone_is_eligible() -> None:
    assert check_eligibility(STUDENT, NO_RULES) == EligibilityResult(eligible=True, reasons=[])


def test_empty_branch_and_year_sets_mean_no_restriction() -> None:
    rules = EligibilityRules(allowed_branches=frozenset(), grad_years=frozenset())

    assert check_eligibility(STUDENT, rules).eligible is True


# ---------------------------------------------------------------- CGPA


@pytest.mark.parametrize(
    ("cgpa", "eligible"),
    [
        ("7.49", False),  # just below
        ("7.50", True),  # exactly at the minimum: "≥", so eligible
        ("7.51", True),
    ],
)
def test_min_cgpa_boundary(cgpa: str, eligible: bool) -> None:
    rules = EligibilityRules(min_cgpa=Decimal("7.5"))

    assert check_eligibility(student(cgpa=Decimal(cgpa)), rules).eligible is eligible


def test_cgpa_reason_shows_cutoff_and_student_value() -> None:
    result = check_eligibility(
        student(cgpa=Decimal("7.20")), EligibilityRules(min_cgpa=Decimal("7.50"))
    )

    assert result.reasons == ["Needs CGPA ≥ 7.5 (you: 7.2)"]


def test_whole_number_cgpa_is_printed_plainly() -> None:
    result = check_eligibility(student(cgpa=Decimal("6")), EligibilityRules(min_cgpa=Decimal("10")))

    assert result.reasons == ["Needs CGPA ≥ 10 (you: 6)"]  # not "1E+1"


# ---------------------------------------------------------------- backlogs


@pytest.mark.parametrize(("backlogs", "eligible"), [(1, True), (2, True), (3, False)])
def test_max_backlogs_boundary(backlogs: int, eligible: bool) -> None:
    rules = EligibilityRules(max_active_backlogs=2)

    assert check_eligibility(student(active_backlogs=backlogs), rules).eligible is eligible


def test_zero_backlogs_allowed_means_none() -> None:
    result = check_eligibility(student(active_backlogs=1), EligibilityRules(max_active_backlogs=0))

    assert result.reasons == ["Needs no active backlogs (you: 1)"]


def test_backlog_reason_with_a_limit() -> None:
    result = check_eligibility(student(active_backlogs=3), EligibilityRules(max_active_backlogs=2))

    assert result.reasons == ["Allows at most 2 active backlogs (you: 3)"]


# ---------------------------------------------------------------- branches


def test_allowed_branch_is_eligible() -> None:
    rules = EligibilityRules(allowed_branches=frozenset({"CSE", "IT"}))

    assert check_eligibility(STUDENT, rules).eligible is True


def test_other_branch_is_not_and_reason_lists_branches_sorted() -> None:
    rules = EligibilityRules(allowed_branches=frozenset({"IT", "CSE"}))

    result = check_eligibility(student(branch_code="ECE"), rules)

    assert result.reasons == ["Open to CSE, IT only (you: ECE)"]


def test_branch_comparison_uses_codes_exactly() -> None:
    # Codes are normalised before they get here; free text like "cse" never matches.
    rules = EligibilityRules(allowed_branches=frozenset({"CSE"}))

    assert check_eligibility(student(branch_code="cse"), rules).eligible is False


# ---------------------------------------------------------------- graduation year


def test_grad_year_in_list_is_eligible() -> None:
    rules = EligibilityRules(grad_years=frozenset({2026, 2027}))

    assert check_eligibility(STUDENT, rules).eligible is True


def test_grad_year_reasons_singular_and_plural() -> None:
    one = check_eligibility(STUDENT, EligibilityRules(grad_years=frozenset({2026})))
    many = check_eligibility(STUDENT, EligibilityRules(grad_years=frozenset({2028, 2026})))

    assert one.reasons == ["For the 2026 batch only (you: 2027)"]
    assert many.reasons == ["For the 2026, 2028 batches only (you: 2027)"]


# ---------------------------------------------------------------- combined


def test_every_failed_rule_gets_its_own_reason_in_a_fixed_order() -> None:
    rules = EligibilityRules(
        min_cgpa=Decimal("8"),
        max_active_backlogs=0,
        grad_years=frozenset({2026}),
        allowed_branches=frozenset({"ECE"}),
    )

    result = check_eligibility(student(active_backlogs=1), rules)

    assert result.eligible is False
    assert result.reasons == [
        "Open to ECE only (you: CSE)",
        "Needs CGPA ≥ 8 (you: 7.5)",
        "Needs no active backlogs (you: 1)",
        "For the 2026 batch only (you: 2027)",
    ]


def test_all_rules_met() -> None:
    rules = EligibilityRules(
        min_cgpa=Decimal("7.5"),
        max_active_backlogs=0,
        grad_years=frozenset({2027}),
        allowed_branches=frozenset({"CSE"}),
    )

    assert check_eligibility(STUDENT, rules) == EligibilityResult(eligible=True, reasons=[])
