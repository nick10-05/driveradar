"""ORM models. Import every model module here so Alembic autogenerate can see it."""

from app.models.application import Application, ApplicationEvent
from app.models.base import Base
from app.models.branch import Branch, BranchAlias
from app.models.drive import Drive, DriveAllowedBranch, DriveEligibility
from app.models.extraction import ExtractionRun
from app.models.profile import StudentProfile
from app.models.user import User, UserSession

__all__ = [
    "Application",
    "ApplicationEvent",
    "Base",
    "Branch",
    "BranchAlias",
    "Drive",
    "DriveAllowedBranch",
    "DriveEligibility",
    "ExtractionRun",
    "StudentProfile",
    "User",
    "UserSession",
]
