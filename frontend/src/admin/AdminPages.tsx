import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";

import { isApiError, type Schemas } from "../api/client";
import {
  describeError,
  useAdminDrive,
  useAdminDrives,
  useCreateDrive,
  useExtract,
  useMe,
  useUpdateDrive,
} from "../api/queries";
import { Loading } from "../components/Loading";
import { formatDeadlineIST } from "../lib/format";
import { DRIVE_STATE_LABEL } from "../lib/status";
import { DriveForm } from "./DriveForm";
import { emptyFields, fromAdminDrive, fromDraft } from "./fields";

/** UX gate only: every /admin endpoint checks the role on the server (403). */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const me = useMe();
  if (me.data?.role !== "admin") return <Navigate to="/" replace />;
  return children;
}

// ---------------------------------------------------------------- list

export function AdminDrivesPage() {
  const drives = useAdminDrives();
  return (
    <section>
      <div className="page-head">
        <h1>Drives (admin)</h1>
        <Link className="button" to="/admin/new">
          + New from notice
        </Link>
      </div>
      {drives.isPending && <Loading />}
      {drives.isError && (
        <p className="status error" role="alert">
          {describeError(drives.error)}
        </p>
      )}
      {drives.data?.length === 0 && <p className="empty">No drives yet. Paste a notice to create one.</p>}
      {drives.data && drives.data.length > 0 && (
        <ul className="drive-list">
          {drives.data.map((d) => (
            <li key={d.id} className="card">
              <div className="drive-head">
                <h3>
                  <Link to={`/admin/drives/${d.id}`}>{d.company}</Link>
                </h3>
                <span className={`badge state-${d.state}`}>{DRIVE_STATE_LABEL[d.state]}</span>
              </div>
              <p className="role">{d.role_title}</p>
              <p className="meta">Deadline {formatDeadlineIST(d.deadline)}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- paste → extract → review → save

const EXTRACT_MESSAGE: Record<Schemas["ExtractOut"]["status"], string> = {
  ok: "AI filled in what it found. Check every field before saving, flagged ones first.",
  disabled: "AI extraction is off on this server. Fill in the fields by hand.",
  error: "The AI service didn't answer. Fill in the fields by hand.",
  invalid: "The AI's answer couldn't be used. Fill in the fields by hand.",
};

export function NewDrivePage() {
  const extract = useExtract();
  const create = useCreateDrive();
  const navigate = useNavigate();
  const [rawText, setRawText] = useState("");
  const [manual, setManual] = useState(false);

  const result = extract.data;
  const reviewing = manual || result !== undefined;

  function onExtract(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setManual(false);
    extract.mutate(rawText);
  }

  if (!reviewing) {
    return (
      <section>
        <h1>New drive</h1>
        <form onSubmit={onExtract} className="card form">
          <label>
            Paste the notice <span className="muted">(email, WhatsApp, portal text; max 8,000 characters)</span>
            <textarea
              rows={12}
              required
              maxLength={8000}
              value={rawText}
              onChange={(e) => setRawText(e.target.value)}
            />
          </label>
          {extract.isError && (
            <p className="error" role="alert">
              {describeError(extract.error)}
            </p>
          )}
          <div className="row">
            <button type="submit" disabled={extract.isPending || !rawText.trim()}>
              {extract.isPending ? "Extracting…" : "Extract with AI"}
            </button>
            <button type="button" className="secondary" disabled={!rawText.trim()} onClick={() => setManual(true)}>
              Fill in manually
            </button>
          </div>
          <p className="muted">
            The AI only reads this notice and suggests fields. You review everything; nothing is
            published until you press Publish.
          </p>
        </form>
      </section>
    );
  }

  return (
    <section>
      <h1>Review the draft</h1>
      {result && (
        <p className={`notice extract-${result.status}`} role="status">
          {EXTRACT_MESSAGE[result.status]}
          {result.issues.length > 0 && ` ${result.issues.length} field(s) flagged.`}
        </p>
      )}
      <details className="card">
        <summary>Notice text</summary>
        <pre className="notice-text">{rawText}</pre>
      </details>
      <DriveForm
        initial={result ? fromDraft(result.draft) : emptyFields()}
        issues={result?.issues}
        submitLabel="Save as draft"
        busy={create.isPending}
        error={create.error}
        onSubmit={(body) =>
          create.mutate(
            { ...body, raw_text: rawText, extraction_run_id: result?.extraction_run_id ?? null },
            { onSuccess: (drive) => navigate(`/admin/drives/${drive.id}`) },
          )
        }
      />
      <p>
        <button type="button" className="link-button" onClick={() => {
            extract.reset();
            setManual(false);
          }}>
          ← Back to the notice
        </button>
      </p>
    </section>
  );
}

// ---------------------------------------------------------------- edit / publish / close

export function AdminDrivePage() {
  const { id = "" } = useParams();
  const drive = useAdminDrive(id);
  const update = useUpdateDrive(id);
  const [dirty, setDirty] = useState(false);
  const [rawText, setRawText] = useState<string | null>(null);

  if (drive.isPending) return <Loading count={1} />;
  if (drive.isError) {
    return (
      <p className="status error" role="alert">
        {isApiError(drive.error, 404) ? "No such drive." : describeError(drive.error)}{" "}
        <Link to="/admin">Back</Link>
      </p>
    );
  }
  const d = drive.data;
  const notice = rawText ?? d.raw_text;

  function changeStatus(status: "published" | "closed") {
    const question =
      status === "published"
        ? "Publish? Eligible students will see this drive."
        : "Close this drive? It disappears from the feed and can't be reopened or edited.";
    if (window.confirm(question)) update.mutate({ status });
  }

  return (
    <section>
      <p>
        <Link to="/admin">← All drives</Link>
      </p>
      <div className="page-head">
        <h1>
          {d.company} <span className="muted">· {d.role_title}</span>
        </h1>
        <span className={`badge state-${d.state}`}>{DRIVE_STATE_LABEL[d.state]}</span>
      </div>

      {d.status !== "closed" && (
        <div className="row actions">
          {d.status === "draft" && (
            <button type="button" disabled={update.isPending || dirty} onClick={() => changeStatus("published")}>
              Publish
            </button>
          )}
          {d.status === "published" && (
            <button type="button" className="danger" disabled={update.isPending || dirty} onClick={() => changeStatus("closed")}>
              Close drive
            </button>
          )}
          {dirty && <span className="muted">Save your changes first.</span>}
        </div>
      )}
      {update.isError && (
        <p className="error" role="alert">
          {describeError(update.error)}
        </p>
      )}
      {d.extraction_run_id && (
        <p className="muted">Linked to extraction run {d.extraction_run_id.slice(0, 8)} (audit log).</p>
      )}

      {d.status === "closed" ? (
        <p className="notice">This drive is closed and read-only.</p>
      ) : (
        <DriveForm
          // Fresh form state whenever the server copy changes (after a save).
          key={d.updated_at}
          initial={fromAdminDrive(d)}
          submitLabel="Save changes"
          busy={update.isPending}
          error={null}
          onDirtyChange={setDirty}
          onSubmit={(body) =>
            update.mutate({ ...body, raw_text: notice }, {
                onSuccess: () => {
                  setDirty(false);
                  setRawText(null);
                },
              })
          }
        >
          <label>
            Notice text
            <textarea
              rows={6}
              maxLength={20000}
              value={notice}
              onChange={(e) => {
                setRawText(e.target.value);
                setDirty(true);
              }}
            />
          </label>
        </DriveForm>
      )}
      {d.status === "closed" && <pre className="notice-text card">{d.raw_text}</pre>}
    </section>
  );
}
