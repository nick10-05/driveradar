import { Link } from "react-router";

import { describeError, useApplications } from "../api/queries";
import { Loading } from "../components/Loading";
import { formatDeadlineIST } from "../lib/format";
import { DRIVE_STATE_LABEL, STATUS_LABEL } from "../lib/status";
import { Timeline } from "./DrivePage";

/** Everything I'm tracking, most recently updated first (the API's order). */
export function TrackerPage() {
  const applications = useApplications();

  if (applications.isPending) return <Loading />;
  if (applications.isError) {
    return (
      <p className="status error" role="alert">
        {describeError(applications.error)}
      </p>
    );
  }

  return (
    <section>
      <h1>My applications</h1>
      {applications.data.length === 0 ? (
        <p className="empty">
          Nothing tracked yet. Open a drive from the <Link to="/">feed</Link> and mark it
          "Interested" or "Applied".
        </p>
      ) : (
        <ul className="drive-list">
          {applications.data.map((entry) => (
            <li key={entry.id} className="card">
              <div className="drive-head">
                <h3>
                  <Link to={`/drives/${entry.drive.id}`}>{entry.drive.company}</Link>
                </h3>
                <span className={`status-badge s-${entry.status}`}>{STATUS_LABEL[entry.status]}</span>
              </div>
              <p className="role">{entry.drive.role_title}</p>
              <p className="meta">
                {DRIVE_STATE_LABEL[entry.drive.state]} · deadline {formatDeadlineIST(entry.drive.deadline)}
              </p>
              {entry.notes && <p className="notes">“{entry.notes}”</p>}
              <details>
                <summary>Timeline ({entry.timeline.length})</summary>
                <Timeline events={entry.timeline} />
              </details>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
