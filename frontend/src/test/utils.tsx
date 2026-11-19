/**
 * Test helpers. Tests stub `fetch` (the network edge), not our hooks, so the real
 * client, error handling, query cache and routing all run.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { vi } from "vitest";

import type { Schemas } from "../api/client";
import { createQueryClient } from "../api/queries";
import { App } from "../App";

type Handler = (request: Request) => Response | Promise<Response>;

export function json(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * Stub fetch with "METHOD /path" → handler (path without the /api prefix). Unknown
 * routes fail the test loudly. Returns the list of requests made, for assertions.
 */
export function mockApi(routes: Record<string, Handler>) {
  const requests: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      requests.push(request.clone());
      const path = new URL(request.url).pathname.replace(/^\/api/, "");
      const handler = routes[`${request.method} ${path}`];
      if (!handler) throw new Error(`Unexpected request: ${request.method} ${path}`);
      return handler(request);
    }),
  );
  return requests;
}

function LocationProbe() {
  return <div data-testid="location">{useLocation().pathname}</div>;
}

/** Render the whole app at `path`, with a fresh cache (no state leaks between tests). */
export function renderApp(path = "/", options: Parameters<typeof createQueryClient>[0] = {}) {
  const queryClient = createQueryClient(options);
  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <App />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}

export const profile: Schemas["ProfileOut"] = {
  branch_code: "CSE",
  cgpa: 7.5,
  active_backlogs: 0,
  grad_year: 2027,
  telegram_linked: false,
};

export function meWith(p: Schemas["ProfileOut"] | null): Schemas["MeOut"] {
  return { id: "11111111-1111-1111-1111-111111111111", email: "asha@example.com", name: "Asha", role: "student", profile: p };
}

export function drive(overrides: Partial<Schemas["StudentDriveOut"]> = {}): Schemas["StudentDriveOut"] {
  return {
    id: crypto.randomUUID(),
    company: "Acme",
    role_title: "SDE Intern",
    ctc_text: null,
    ctc_lpa: 12,
    location: "Bengaluru",
    apply_link: "https://acme.example/apply",
    deadline: "2099-01-01T11:30:00Z",
    state: "open",
    eligibility: { min_cgpa: null, max_active_backlogs: null, grad_years: [], allowed_branches: [] },
    eligible: true,
    reasons: [],
    ...overrides,
  };
}
