import { useState, type FormEvent, type ReactNode } from "react";

import type { Schemas } from "../api/client";
import { describeError, useBranches } from "../api/queries";
import { ISSUE_FIELD, toBody, type DriveFields } from "./fields";

type Issue = Schemas["FieldIssue"];
type Body = Extract<ReturnType<typeof toBody>, { ok: true }>["body"];

const ISSUE_LABEL: Record<Issue["kind"], string> = {
  verify: "Check",
  invalid: "Rejected",
  missing: "Missing",
};

/**
 * The review form. The AI's flags (per-field issues from the normaliser) sit next to the
 * fields they're about, so the admin checks exactly what was uncertain. Nothing here is
 * saved or published without the admin pressing a button (DESIGN D9).
 */
export function DriveForm(props: {
  initial: DriveFields;
  issues?: Issue[];
  submitLabel: string;
  busy: boolean;
  error: unknown;
  onSubmit: (body: Body) => void;
  onDirtyChange?: (dirty: boolean) => void;
  children?: ReactNode; // extra fields (e.g. the notice text on the edit page)
}) {
  const branches = useBranches();
  const [fields, setFields] = useState(props.initial);
  const [errors, setErrors] = useState<Partial<Record<keyof DriveFields, string>>>({});

  const issuesFor = (field: keyof DriveFields) =>
    (props.issues ?? []).filter((issue) => ISSUE_FIELD[issue.field] === field);
  const otherIssues = (props.issues ?? []).filter((issue) => !(issue.field in ISSUE_FIELD));

  function update(patch: Partial<DriveFields>) {
    setFields((current) => ({ ...current, ...patch }));
    props.onDirtyChange?.(true);
  }
  const text = (field: keyof DriveFields) => ({
    value: fields[field] as string,
    onChange: (e: { target: { value: string } }) => update({ [field]: e.target.value }),
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const converted = toBody(fields);
    if (!converted.ok) {
      setErrors(converted.errors);
      return;
    }
    setErrors({});
    props.onSubmit(converted.body);
  }

  const field = (name: keyof DriveFields, label: string, input: ReactNode, hint?: string) => {
    const issues = issuesFor(name);
    const caption = (
      <span>
        {label} {hint && <span className="muted">{hint}</span>}
      </span>
    );
    return (
      <div className={`field ${issues.map((i) => `issue-${i.kind}`).join(" ")}`}>
        {name === "allowed_branches" ? (
          // A group of checkboxes, each with its own label: no wrapping <label>
          // (nested labels are invalid HTML and break screen readers).
          <div role="group" aria-label={label} className="field">
            {caption}
            {input}
          </div>
        ) : (
          <label>
            {caption}
            {input}
          </label>
        )}
        {issues.map((issue) => (
          <p key={issue.message} className={`issue issue-${issue.kind}`}>
            <strong>{ISSUE_LABEL[issue.kind]}:</strong> {issue.message}
          </p>
        ))}
        {errors[name] && <p className="error">{errors[name]}</p>}
      </div>
    );
  };

  return (
    <form onSubmit={onSubmit} className="card form" noValidate>
      {otherIssues.length > 0 && (
        <ul className="issue-list">
          {otherIssues.map((issue) => (
            <li key={`${issue.field}-${issue.message}`} className={`issue issue-${issue.kind}`}>
              <strong>{issue.field}:</strong> {issue.message}
            </li>
          ))}
        </ul>
      )}
      {field("company", "Company", <input {...text("company")} maxLength={200} />)}
      {field("role_title", "Role", <input {...text("role_title")} maxLength={200} />)}
      {field("deadline", "Deadline", <input type="datetime-local" {...text("deadline")} />, "(IST)")}
      {field("ctc_text", "CTC as written", <input {...text("ctc_text")} maxLength={200} />, "(optional)")}
      {field("ctc_lpa", "CTC in LPA", <input inputMode="decimal" {...text("ctc_lpa")} />, "(optional, number)")}
      {field("location", "Location", <input {...text("location")} maxLength={200} />, "(optional)")}
      {field("apply_link", "Apply link", <input type="url" {...text("apply_link")} />, "(optional, https://…)")}
      {field(
        "source",
        "Source",
        <select {...text("source")}>
          <option value="">—</option>
          <option value="email">TPO email</option>
          <option value="whatsapp">WhatsApp</option>
          <option value="portal">Portal</option>
          <option value="telegram">Telegram</option>
          <option value="other">Other</option>
        </select>,
      )}

      <fieldset>
        <legend>Eligibility rules (empty = no restriction)</legend>
        {field("min_cgpa", "Minimum CGPA", <input inputMode="decimal" {...text("min_cgpa")} />)}
        {field("max_active_backlogs", "Max active backlogs", <input inputMode="numeric" {...text("max_active_backlogs")} />)}
        {field("grad_years", "Graduation years", <input {...text("grad_years")} placeholder="2026, 2027" />)}
        {field(
          "allowed_branches",
          "Branches",
          <span className="checks">
            {branches.isError && <span className="error">{describeError(branches.error)}</span>}
            {branches.data?.map((b) => (
              <label key={b.code} className="check">
                <input
                  type="checkbox"
                  checked={fields.allowed_branches.includes(b.code)}
                  onChange={(e) =>
                    update({
                      allowed_branches: e.target.checked
                        ? [...fields.allowed_branches, b.code]
                        : fields.allowed_branches.filter((c) => c !== b.code),
                    })
                  }
                />
                {b.code}
              </label>
            ))}
          </span>,
          fields.allowed_branches.length === 0 ? "(none ticked = all branches)" : undefined,
        )}
      </fieldset>

      {props.children}

      {props.error ? (
        <p className="error" role="alert">
          {describeError(props.error)}
        </p>
      ) : null}
      <button type="submit" disabled={props.busy}>
        {props.busy ? "Saving…" : props.submitLabel}
      </button>
    </form>
  );
}
