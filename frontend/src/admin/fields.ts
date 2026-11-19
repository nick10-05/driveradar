/**
 * Admin drive form: field values as strings (what inputs hold) and the conversion to an
 * API body. Pure functions, so the conversions are unit-tested without rendering.
 */
import type { Schemas } from "../api/client";
import { fromISTInput, toISTInput } from "../lib/format";

export type DriveFields = {
  company: string;
  role_title: string;
  ctc_text: string;
  ctc_lpa: string;
  location: string;
  apply_link: string;
  deadline: string; // datetime-local value, IST wall-clock
  source: string;
  min_cgpa: string;
  max_active_backlogs: string;
  grad_years: string; // "2026, 2027"
  allowed_branches: string[]; // codes; empty = open to all
};

type Common = Omit<Schemas["DriveCreate"], "raw_text" | "extraction_run_id">;

const str = (value: string | number | null | undefined) => (value === null || value === undefined ? "" : String(value));

export function emptyFields(): DriveFields {
  return fromDraft(null);
}

/** From an extraction draft (every field may be null: the model abstained or was off). */
export function fromDraft(draft: Schemas["DraftDrive"] | null): DriveFields {
  return {
    company: str(draft?.company),
    role_title: str(draft?.role_title),
    ctc_text: str(draft?.ctc_text),
    ctc_lpa: str(draft?.ctc_lpa),
    location: str(draft?.location),
    apply_link: str(draft?.apply_link),
    deadline: toISTInput(draft?.deadline),
    source: "",
    min_cgpa: str(draft?.eligibility?.min_cgpa),
    max_active_backlogs: str(draft?.eligibility?.max_active_backlogs),
    grad_years: (draft?.eligibility?.grad_years ?? []).join(", "),
    allowed_branches: [...(draft?.eligibility?.allowed_branches ?? [])],
  };
}

export function fromAdminDrive(drive: Schemas["AdminDriveOut"]): DriveFields {
  return {
    ...fromDraft({ ...drive, eligibility: drive.eligibility }),
    source: str(drive.source),
  };
}

export type Converted = { ok: true; body: Common } | { ok: false; errors: Partial<Record<keyof DriveFields, string>> };

/** Strings → API body. Client checks are only for quick feedback; the server re-validates. */
export function toBody(fields: DriveFields): Converted {
  const errors: Partial<Record<keyof DriveFields, string>> = {};
  const deadline = fromISTInput(fields.deadline);
  if (!fields.company.trim()) errors.company = "Required.";
  if (!fields.role_title.trim()) errors.role_title = "Required.";
  if (!deadline) errors.deadline = "Pick a date and time (IST).";

  const number = (key: keyof DriveFields, value: string, integer = false) => {
    if (!value.trim()) return null;
    const n = Number(value);
    if (!Number.isFinite(n) || (integer && !Number.isInteger(n))) {
      errors[key] = integer ? "Must be a whole number." : "Must be a number.";
      return null;
    }
    return n;
  };

  const tokens = fields.grad_years.split(/[\s,]+/).filter(Boolean);
  const gradYears = tokens.map(Number);
  if (gradYears.some((y) => !Number.isInteger(y) || y < 2000 || y > 2100)) {
    errors.grad_years = "Years like 2026, 2027.";
  }

  const body: Common = {
    company: fields.company.trim(),
    role_title: fields.role_title.trim(),
    ctc_text: fields.ctc_text.trim() || null,
    ctc_lpa: number("ctc_lpa", fields.ctc_lpa),
    location: fields.location.trim() || null,
    apply_link: fields.apply_link.trim() || null,
    deadline: deadline ?? "",
    source: (fields.source || null) as Common["source"],
    eligibility: {
      min_cgpa: number("min_cgpa", fields.min_cgpa),
      max_active_backlogs: number("max_active_backlogs", fields.max_active_backlogs, true),
      grad_years: [...new Set(gradYears)].sort((a, b) => a - b),
      allowed_branches: fields.allowed_branches,
    },
  };
  return Object.keys(errors).length > 0 ? { ok: false, errors } : { ok: true, body };
}

/** The normaliser's issue field names → the form field they belong to. */
export const ISSUE_FIELD: Record<string, keyof DriveFields> = {
  company: "company",
  role_title: "role_title",
  ctc_text: "ctc_text",
  ctc_lpa: "ctc_lpa",
  location: "location",
  apply_link: "apply_link",
  deadline: "deadline",
  "eligibility.min_cgpa": "min_cgpa",
  "eligibility.max_active_backlogs": "max_active_backlogs",
  "eligibility.grad_years": "grad_years",
  "eligibility.allowed_branches": "allowed_branches",
};
