/**
 * Typed API client (DESIGN §7.6).
 *
 * `paths` is generated from the backend's OpenAPI schema (`npm run gen:api`), so every
 * URL, request body and response here is type-checked against the real API: rename a
 * field in a Pydantic model, re-export, and `tsc` points at every screen that breaks.
 *
 * Interview notes:
 * - Same-origin `/api` (dev: Vite proxy, prod: Vercel rewrite). The session cookie is
 *   HttpOnly, so this code never sees it: the browser attaches it to same-origin requests
 *   (fetch's default `credentials: "same-origin"`). No token in localStorage = nothing
 *   for an XSS payload to steal.
 * - The browser adds the `Origin` header itself on POST/PUT/PATCH; JavaScript can't set
 *   or fake it, which is why the backend can trust it for CSRF checks.
 */
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

export const api = createClient<paths>({
  // Absolute URL so the same code also works under Node in tests (Node's Request
  // rejects relative URLs; browsers resolve them against the page anyway).
  baseUrl: `${globalThis.location?.origin ?? "http://localhost"}/api`,
  // Looked up on every call (not captured once), so tests can stub `fetch`.
  fetch: (request) => globalThis.fetch(request),
});

/** Any non-2xx answer from the API, with a message safe to show to the user. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * Render's free tier sleeps after ~15 idle minutes and takes ~30 s to wake. Meanwhile the
 * Vercel proxy answers 502 (sometimes 503/504) at once. These statuses mean "try again
 * soon", not "broken", so queries retry them for about a minute (queries.ts).
 */
const WAKING_STATUSES: ReadonlySet<number> = new Set([502, 503, 504]);
export const WAKING_MESSAGE =
  "The server is waking up (free hosting, up to a minute). Try again in a few seconds.";

export function isWakingUp(error: unknown): boolean {
  return error instanceof ApiError && WAKING_STATUSES.has(error.status);
}

type ValidationItem = { loc?: (string | number)[]; msg?: string };

/** FastAPI errors: `{"detail": "text"}` or, for 422, `{"detail": [{loc, msg}, ...]}`. */
export function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return (detail as ValidationItem[])
      .map((item) => {
        const field = item.loc?.filter((part) => part !== "body").join(".");
        return field ? `${field}: ${item.msg ?? "invalid"}` : (item.msg ?? "Invalid value");
      })
      .join("; ");
  }
  if (status === 429) return "Too many attempts. Try again later.";
  if (WAKING_STATUSES.has(status)) return WAKING_MESSAGE;
  if (status >= 500) return "The server had a problem. Try again in a minute.";
  return `Request failed (${status})`;
}

/**
 * Turn openapi-fetch's `{data, error, response}` into "data or throw", which is what
 * TanStack Query expects (a thrown error = the query/mutation failed).
 */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, error));
  return data as T;
}

export function isApiError(error: unknown, status?: number): error is ApiError {
  return error instanceof ApiError && (status === undefined || error.status === status);
}
