import { useIsFetching } from "@tanstack/react-query";

import { isWakingUp } from "../api/client";

/**
 * Shown while any query is being retried because the backend is waking up (Render free
 * tier). Without it the first visit after a quiet spell looks like an endless spinner
 * or an error. It reads TanStack Query's own retry state: no extra request, no polling.
 */
export function WakingBanner() {
  const retrying = useIsFetching({
    predicate: (query) => query.state.fetchFailureCount > 0 && isWakingUp(query.state.fetchFailureReason),
  });
  if (retrying === 0) return null;
  return (
    <p className="waking" role="status">
      Waking up the server… Free hosting sleeps when idle, so this can take up to a minute.
    </p>
  );
}
