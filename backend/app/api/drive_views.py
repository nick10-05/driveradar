"""ORM Drive / Application → response models, shared by the routers."""

from datetime import datetime

from app.models import Application, Drive
from app.schemas.application import ApplicationOut, TrackerEntryOut
from app.schemas.drive import (
    AdminDriveOut,
    EligibilityRulesOut,
    StudentDriveDetailOut,
    StudentDriveOut,
)
from app.services.drives import drive_state
from app.services.eligibility import EligibilityResult


def application_view(application: Application) -> ApplicationOut:
    return ApplicationOut.model_validate(_application_fields(application))


def tracker_entry_view(application: Application, drive: Drive, now: datetime) -> TrackerEntryOut:
    return TrackerEntryOut.model_validate(
        {
            **_application_fields(application),
            "drive": {
                "id": drive.id,
                "company": drive.company,
                "role_title": drive.role_title,
                "deadline": drive.deadline,
                "state": drive_state(drive, now),
            },
        }
    )


def _application_fields(application: Application) -> dict[str, object]:
    return {
        "id": application.id,
        "drive_id": application.drive_id,
        "status": application.status,
        "notes": application.notes,
        "updated_at": application.updated_at,
        "timeline": [
            {"from_status": e.from_status, "to_status": e.to_status, "at": e.at}
            for e in application.events
        ],
    }


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
