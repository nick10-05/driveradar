import { useState } from "react";
import { Link, useParams } from "react-router";

import { isApiError, type Schemas } from "../api/client";
import { describeError, useDrive, useSetApplication, type Status } from "../api/queries";
import { Loading } from "../components/Loading";
import { formatCtc, formatDeadlineIST, timeLeft } from "../lib/format";
import { DRIVE_STATE_LABEL, ENDS_TRACKING, MOVE_LABEL, STATUS_LABEL } from "../lib/status";

export function DrivePage() {
  const { id = "" } = useParams();
  const drive = useDrive(id);

  if (drive.isPending) return <Loading count={1} />;
  if (drive.isError) {
    const message = isApiError(drive.error, 404) ? "This drive doesn't exist." : describeError(drive.error);
    return (
      <p className="status error" role="alert">
        {message} <Link to="/">Back to drives</Link>
      </p>
    );
  }

  const d = drive.data;
  const ctc = formatCtc(d.ctc_text, d.ctc_lpa);
  return (
    <article className="drive-page">
      <p>
        <Link to="/">← Drives</Link>
      </p>
      <div className="drive-head">
        <h1>{d.company}</h1>
        <span className={`badge ${d.eligible ? "ok" : "no"}`}>{d.eligible ? "Eligible" : "Not eligible"}</span>
      </div>
      <p className="role">{d.role_title}</p>
      {ctc || d.location ? <p className="meta">{[ctc, d.location].filter(Boolean).join(" · ")}</p> : null}
      <p>
        Deadline: <time dateTime={d.deadline}>{formatDeadlineIST(d.deadline)}</time>{" "}
        <span className="muted">
          ({d.state === "open" ? timeLeft(d.deadline) : DRIVE_STATE_LABEL[d.state]})
        </span>
      </p>
      {!d.eligible && (
        <ul className="reasons" aria-label="Why not">
          {d.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {d.apply_link && d.state === "open" && (
        <a className="apply" href={d.apply_link} target="_blank" rel="noopener noreferrer">
          Apply on company site ↗
        </a>
      )}

      <Tracker drive={d} />

      <h2>Original notice</h2>
      {/* Rendered as text (React escapes it): a notice can't inject HTML or scripts. */}
      <pre className="notice-text card">{d.raw_text}</pre>
    </article>
  );
}

function Tracker({ drive }: { drive: Schemas["StudentDriveDetailOut"] }) {
  const setApplication = useSetApplication(drive.id);
  const application = drive.application;
  const [notes, setNotes] = useState(application?.notes ?? "");

  function move(status: Status) {
    if (ENDS_TRACKING.has(status) && !window.confirm(`Mark as "${STATUS_LABEL[status]}"? This can't be undone.`)) {
      return;
    }
    setApplication.mutate({ status });
  }

  const notesChanged = application !== null && notes !== (application.notes ?? "");

  return (
    <section className="card tracker" aria-labelledby="tracker-heading">
      <h2 id="tracker-heading">Your status</h2>
      {application ? (
        <p>
          <span className={`status-badge s-${application.status}`}>{STATUS_LABEL[application.status]}</span>
        </p>
      ) : (
        <p className="muted">Not tracking this drive yet.</p>
      )}

      {/* One button per move the server says it will accept; none in a final state. */}
      {drive.next_statuses.length > 0 && (
        <div className="moves" role="group" aria-label="Update status">
          {drive.next_statuses.map((status) => (
            <button
              key={status}
              type="button"
              className={ENDS_TRACKING.has(status) && status !== "offer" ? "secondary" : ""}
              disabled={setApplication.isPending}
              onClick={() => move(status)}
            >
              {MOVE_LABEL[status]}
            </button>
          ))}
        </div>
      )}
      {setApplication.isError && (
        <p className="error" role="alert">
          {describeError(setApplication.error)}
        </p>
      )}

      {application && (
        <>
          <label>
            Notes <span className="muted">(only you see these)</span>
            <textarea
              rows={3}
              maxLength={2000}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>
          {notesChanged && (
            <button
              type="button"
              disabled={setApplication.isPending}
              // Same status = notes-only update on the server, no timeline event.
              onClick={() => setApplication.mutate({ status: application.status, notes: notes.trim() || null })}
            >
              Save notes
            </button>
          )}
          <Timeline events={application.timeline} />
        </>
      )}
    </section>
  );
}

export function Timeline({ events }: { events: Schemas["EventOut"][] }) {
  return (
    <ol className="timeline" aria-label="Timeline">
      {events.map((e) => (
        <li key={`${e.at}-${e.to_status}`}>
          <strong>{STATUS_LABEL[e.to_status]}</strong>{" "}
          <span className="muted">
            {e.from_status ? `from ${STATUS_LABEL[e.from_status]}` : "started tracking"} ·{" "}
            <time dateTime={e.at}>{formatDeadlineIST(e.at)}</time>
          </span>
        </li>
      ))}
    </ol>
  );
}
