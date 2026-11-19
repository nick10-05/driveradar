import { Link, Navigate } from "react-router";

import { isApiError, type Schemas } from "../api/client";
import { describeError, useDrives, useMe } from "../api/queries";
import { formatCtc, formatDeadlineIST, isUrgent, timeLeft } from "../lib/format";

type Drive = Schemas["StudentDriveOut"];

/**
 * The student's feed. Eligibility is decided by the server (`check_eligibility`, pure
 * Python); this page only displays the result and the reasons. It never re-computes
 * eligibility, so there is one source of truth and nothing for a student to tamper with.
 */
export function FeedPage() {
  const me = useMe();
  const hasProfile = Boolean(me.data?.profile);
  const drives = useDrives(hasProfile);

  // No profile → the API answers 409; don't even ask, send them to the form.
  // An admin (the TPO, not in the batch) has no profile and works in the admin area.
  if (me.data && !hasProfile) {
    return <Navigate to={me.data.role === "admin" ? "/admin" : "/profile"} replace />;
  }
  if (drives.isError && isApiError(drives.error, 409)) return <Navigate to="/profile" replace />;

  if (drives.isPending) return <p className="status">Loading drives…</p>;
  if (drives.isError) {
    return (
      <p className="status error" role="alert">
        {describeError(drives.error)}{" "}
        <button type="button" className="link-button" onClick={() => drives.refetch()}>
          Retry
        </button>
      </p>
    );
  }

  // The API already sorts: eligible first, then soonest deadline. Keep that order.
  const eligible = drives.data.filter((d) => d.eligible);
  const ineligible = drives.data.filter((d) => !d.eligible);

  if (drives.data.length === 0) {
    return (
      <section>
        <h1>Open drives</h1>
        <p className="empty">No open drives right now. New ones appear here once published.</p>
      </section>
    );
  }

  return (
    <section>
      <h1>Open drives</h1>
      <h2>
        You're eligible <span className="count">{eligible.length}</span>
      </h2>
      {eligible.length === 0 ? (
        <p className="empty">None of the open drives match your profile yet.</p>
      ) : (
        <ul className="drive-list">
          {eligible.map((drive) => (
            <DriveCard key={drive.id} drive={drive} />
          ))}
        </ul>
      )}
      {ineligible.length > 0 && (
        <details className="ineligible">
          <summary>
            Not eligible <span className="count">{ineligible.length}</span>
          </summary>
          <ul className="drive-list">
            {ineligible.map((drive) => (
              <DriveCard key={drive.id} drive={drive} />
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function DriveCard({ drive }: { drive: Drive }) {
  const ctc = formatCtc(drive.ctc_text, drive.ctc_lpa);
  const urgent = isUrgent(drive.deadline);
  return (
    <li className={`card drive ${drive.eligible ? "" : "is-ineligible"}`}>
      <div className="drive-head">
        <h3>
          <Link to={`/drives/${drive.id}`}>{drive.company}</Link>
        </h3>
        <span className={`badge ${drive.eligible ? "ok" : "no"}`}>
          {drive.eligible ? "Eligible" : "Not eligible"}
        </span>
      </div>
      <p className="role">{drive.role_title}</p>
      <p className="meta">
        {[ctc, drive.location].filter(Boolean).join(" · ")}
      </p>
      <p className={`deadline ${urgent ? "urgent" : ""}`}>
        Deadline: <time dateTime={drive.deadline}>{formatDeadlineIST(drive.deadline)}</time>{" "}
        <span className="muted">({timeLeft(drive.deadline)})</span>
      </p>
      {!drive.eligible && drive.reasons.length > 0 && (
        <ul className="reasons" aria-label="Why not">
          {drive.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      {drive.eligible && drive.apply_link && (
        // noopener: the company page can't script this tab; noreferrer: no Referer leak.
        <a className="apply" href={drive.apply_link} target="_blank" rel="noopener noreferrer">
          Apply on company site ↗
        </a>
      )}
    </li>
  );
}
