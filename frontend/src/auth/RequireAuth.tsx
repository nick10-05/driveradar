import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { describeError, useMe } from "../api/queries";

/**
 * Gate for logged-in pages. This is UX only: the real check is on the server (every
 * endpoint requires the session cookie). Hiding a page in React protects nothing.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const me = useMe();
  const location = useLocation();

  if (me.isPending) return <p className="status">Loading…</p>;
  if (me.isError) {
    return (
      <p className="status error" role="alert">
        {describeError(me.error)}
      </p>
    );
  }
  if (me.data === null) {
    // Remember where they were going. Passed in router state (not ?next=), so a link
    // from outside can't turn the login page into an open redirect.
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return children;
}

/**
 * Only internal paths. Never "//evil.example" or "/\evil.example" (browsers read both as
 * another host) or a full URL.
 */
export function safeRedirect(from: unknown): string {
  if (typeof from !== "string" || !from.startsWith("/")) return "/";
  if (from.startsWith("//") || from.startsWith("/\\")) return "/";
  return from;
}
