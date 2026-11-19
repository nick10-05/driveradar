"""ORM Drive → response models, shared by the student and admin routers."""

from datetime import datetime

from app.models import Drive
from app.schemas.drive import (
    AdminDriveOut,
    EligibilityRulesOut,
    StudentDriveDetailOut,
    StudentDriveOut,
)
from app.services.drives import drive_state
from app.services.eligibility import EligibilityResult


def _common(drive: Drive, now: datetime) -> dict[str, object]:
    return {
        "id": drive.id,
        "company": drive.company,
        "role_title": drive.role_title,
        "ctc_text": drive.ctc_text,
        "ctc_lpa": drive.ctc_lpa,
        "location": drive.location,
        "apply_link": drive.apply_link,
        "deadline": drive.deadline,
        "state": drive_state(drive, now),
        "eligibility": EligibilityRulesOut(
            min_cgpa=drive.eligibility.min_cgpa,
            max_active_backlogs=drive.eligibility.max_active_backlogs,
            grad_years=drive.eligibility.grad_years or [],
            allowed_branches=[branch.branch_code for branch in drive.allowed_branches],
        ),
    }


def admin_view(drive: Drive, now: datetime) -> AdminDriveOut:
    return AdminDriveOut.model_validate(
        {
            **_common(drive, now),
            "status": drive.status,
            "source": drive.source,
            "raw_text": drive.raw_text,
            "extraction_run_id": drive.extraction_run_id,
            "closed_at": drive.closed_at,
            "created_at": drive.created_at,
            "updated_at": drive.updated_at,
        }
    )


def student_view(drive: Drive, result: EligibilityResult, now: datetime) -> StudentDriveOut:
    return StudentDriveOut.model_validate(
        {**_common(drive, now), "eligible": result.eligible, "reasons": result.reasons}
    )


def student_detail_view(
    drive: Drive, result: EligibilityResult, now: datetime
) -> StudentDriveDetailOut:
    return StudentDriveDetailOut.model_validate(
        {
            **_common(drive, now),
            "eligible": result.eligible,
            "reasons": result.reasons,
            "raw_text": drive.raw_text,
        }
    )
