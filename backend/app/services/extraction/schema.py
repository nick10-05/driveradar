"""Data shapes of the extraction pipeline (DESIGN §4.4, §4.5).

Interview notes:
- ExtractedNotice is what the LLM must return. Every field is nullable: the prompt says
  "use null if the notice doesn't say it", so "not stated" has a legal answer and the
  model isn't pushed to invent one. Its JSON schema is sent to the provider as the
  required response format.
- The LLM output is treated like user input: parsed with Pydantic, then checked again by
  the normaliser. Types alone don't make a value true.
- `evidence` holds a short verbatim quote per key field. The normaliser checks each quote
  really appears in the notice: a cheap guard against hallucinated values.
- DraftDrive is the normaliser's output, already in our own vocabulary (UTC datetimes,
  branch codes, Decimals). It pre-fills the admin's review form; nothing is saved as a
  drive until the admin submits it.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.drive import CtcLpa
from app.schemas.profile import Cgpa

ExtractionStatus = Literal["ok", "invalid", "error", "disabled"]
IssueKind = Literal["verify", "invalid", "missing"]

# Keys the evidence check covers (DESIGN §4.5 step 1).
EVIDENCE_KEYS = (
    "company",
    "deadline",
    "ctc",
    "min_cgpa",
    "branches",
    "max_active_backlogs",
    "grad_years",
)


class ExtractedNotice(BaseModel):
    """The LLM's answer. Extra keys are ignored; every field may be null."""

    model_config = ConfigDict(extra="ignore")

    company: str | None = None
    role_title: str | None = None
    ctc_text: str | None = Field(None, description="Verbatim, e.g. '6-8 LPA + bonus'")
    ctc_lpa: float | None = Field(None, description="Lower bound in LPA, if a number is stated")
    location: str | None = None
    apply_link: str | None = None
    deadline_text: str | None = Field(None, description="Verbatim deadline text")
    deadline_local: str | None = Field(
        None, description="ISO-8601 datetime as written; no timezone unless the notice says one"
    )
    min_cgpa: float | None = None
    branches_raw: list[str] | None = Field(None, description="Branches exactly as written")
    max_active_backlogs: int | None = None
    grad_years: list[int] | None = None
    evidence: dict[str, str] = Field(
        default_factory=dict,
        description=f"Short verbatim quote from the notice for each non-null field among: "
        f"{', '.join(EVIDENCE_KEYS)}",
    )


class FieldIssue(BaseModel):
    """A flag shown next to a field in the review form.

    kind: "verify" = value kept but check it (e.g. no evidence quote);
          "invalid" = value rejected and left empty (or a rule could not be mapped);
          "missing" = a required drive field was not found.
    """

    field: str  # draft field path, e.g. "deadline" or "eligibility.min_cgpa"
    kind: IssueKind
    message: str


class DraftEligibility(BaseModel):
    min_cgpa: Cgpa | None = None
    max_active_backlogs: int | None = None
    grad_years: list[int] = []
    allowed_branches: list[str] = []


class DraftDrive(BaseModel):
    """Pre-filled review form. Same field names as DriveCreate, all optional."""

    company: str | None = None
    role_title: str | None = None
    ctc_text: str | None = None
    ctc_lpa: CtcLpa | None = None
    location: str | None = None
    apply_link: str | None = None
    deadline: datetime | None = None  # UTC
    eligibility: DraftEligibility = DraftEligibility()


class ExtractionResult(BaseModel):
    """What an Extractor returns. `notice` is set only when status == "ok"."""

    status: ExtractionStatus
    notice: ExtractedNotice | None = None
    rejected_fields: list[str] = []  # fields dropped because the model's value had a bad type
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None  # short, safe code like "timeout" or "http_429"; never content


class ExtractIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 8,000 chars bounds cost and latency per call (DESIGN §4.7).
    raw_text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000)
    ]


class ExtractOut(BaseModel):
    """POST /admin/drives/extract. Always 200: on any AI failure the draft is just empty."""

    extraction_run_id: uuid.UUID
    status: ExtractionStatus
    provider: str
    model: str | None
    draft: DraftDrive
    issues: list[FieldIssue]


def quantize2(value: float) -> Decimal:
    """Float from JSON → Decimal with 2 places (via str, so 7.5 stays exactly 7.50)."""
    return Decimal(str(value)).quantize(Decimal("0.01"))
