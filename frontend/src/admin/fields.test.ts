import { describe, expect, it } from "vitest";

import { emptyFields, fromDraft, toBody, type DriveFields } from "./fields";

const filled = (overrides: Partial<DriveFields> = {}): DriveFields => ({
  ...emptyFields(),
  company: " Acme ",
  role_title: "SDE",
  deadline: "2026-12-05T17:00",
  ...overrides,
});

describe("fromDraft", () => {
  it("turns an extraction draft into form strings, deadline in IST", () => {
    const fields = fromDraft({
      company: "Acme",
      role_title: null,
      ctc_text: null,
      ctc_lpa: 12.5,
      location: null,
      apply_link: null,
      deadline: "2026-12-05T11:30:00Z",
      eligibility: { min_cgpa: 7, max_active_backlogs: 0, grad_years: [2026, 2027], allowed_branches: ["CSE"] },
    });
    expect(fields).toMatchObject({
      company: "Acme",
      role_title: "", // abstained → empty, for the admin to fill
      ctc_lpa: "12.5",
      deadline: "2026-12-05T17:00",
      min_cgpa: "7",
      max_active_backlogs: "0", // 0 is a real rule ("no backlogs"), not "empty"
      grad_years: "2026, 2027",
      allowed_branches: ["CSE"],
    });
  });

  it("gives an empty form when the AI was off", () => {
    expect(fromDraft(null)).toEqual(emptyFields());
  });
});

describe("toBody", () => {
  it("trims, turns empty optional fields into null and sends an explicit IST offset", () => {
    const result = toBody(filled());
    expect(result).toEqual({
      ok: true,
      body: {
        company: "Acme",
        role_title: "SDE",
        ctc_text: null,
        ctc_lpa: null,
        location: null,
        apply_link: null,
        deadline: "2026-12-05T17:00:00+05:30",
        source: null,
        eligibility: { min_cgpa: null, max_active_backlogs: null, grad_years: [], allowed_branches: [] },
      },
    });
  });

  it("parses numbers and graduation years (deduplicated, sorted)", () => {
    const result = toBody(
      filled({ ctc_lpa: "6.5", min_cgpa: "7.25", max_active_backlogs: "0", grad_years: "2027,2026 2027" }),
    );
    expect(result.ok && result.body).toMatchObject({
      ctc_lpa: 6.5,
      eligibility: { min_cgpa: 7.25, max_active_backlogs: 0, grad_years: [2026, 2027] },
    });
  });

  it("reports every problem at once instead of sending", () => {
    const result = toBody(
      filled({ company: " ", deadline: "", ctc_lpa: "lots", max_active_backlogs: "1.5", grad_years: "27" }),
    );
    expect(result).toEqual({
      ok: false,
      errors: {
        company: "Required.",
        deadline: "Pick a date and time (IST).",
        ctc_lpa: "Must be a number.",
        max_active_backlogs: "Must be a whole number.",
        grad_years: "Years like 2026, 2027.",
      },
    });
  });
});
