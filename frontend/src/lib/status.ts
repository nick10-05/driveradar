import type { Status } from "../api/queries";

/**
 * Words only. Which moves are allowed comes from the server (`next_statuses`); this file
 * must never decide that, or the TypeScript and Python rules could drift apart.
 */
export const STATUS_LABEL: Record<Status, string> = {
  interested: "Interested",
  applied: "Applied",
  test: "Test",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

/** Button text for moving TO a status. */
export const MOVE_LABEL: Record<Status, string> = {
  interested: "I'm interested",
  applied: "I applied",
  test: "Got a test",
  interview: "Got an interview",
  offer: "Got an offer 🎉",
  rejected: "Rejected",
  withdrawn: "Withdraw",
};

/** Moves with no way back (asked to confirm first). The server enforces it anyway. */
export const ENDS_TRACKING: ReadonlySet<Status> = new Set(["offer", "rejected", "withdrawn"]);

export const DRIVE_STATE_LABEL = {
  draft: "Draft",
  open: "Open",
  expired: "Deadline passed",
  closed: "Closed",
} as const;
