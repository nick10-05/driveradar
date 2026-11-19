/**
 * Backend cold start (Render free tier sleeps; the Vercel proxy answers 502 meanwhile).
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ApiError, errorMessage, isWakingUp } from "./api/client";
import { retryDelay, shouldRetry } from "./api/queries";
import { json, meWith, mockApi, profile, renderApp } from "./test/utils";

describe("retry policy", () => {
  it.each([502, 503, 504])("keeps retrying %i for about a minute, then gives up", (status) => {
    const error = new ApiError(status, "x");
    expect(isWakingUp(error)).toBe(true);
    expect(shouldRetry(0, error)).toBe(true);
    expect(shouldRetry(9, error)).toBe(true);
    expect(shouldRetry(10, error)).toBe(false);
    const total = Array.from({ length: 10 }, (_, n) => retryDelay(n)).reduce((a, b) => a + b, 0);
    expect(total).toBeGreaterThanOrEqual(45_000); // Render needs ~30 s
    expect(total).toBeLessThanOrEqual(75_000);
  });

  it("retries other server or network errors once, and never a 4xx", () => {
    expect(shouldRetry(0, new ApiError(500, "x"))).toBe(true);
    expect(shouldRetry(1, new ApiError(500, "x"))).toBe(false);
    expect(shouldRetry(0, new TypeError("Failed to fetch"))).toBe(true);
    expect(shouldRetry(1, new TypeError("Failed to fetch"))).toBe(false);
    for (const status of [400, 401, 403, 404, 409, 422, 429]) {
      expect(shouldRetry(0, new ApiError(status, "x"))).toBe(false);
    }
  });

  it("backs off 1 s, 2 s, 4 s, then 8 s", () => {
    expect([0, 1, 2, 3, 4, 9].map(retryDelay)).toEqual([1000, 2000, 4000, 8000, 8000, 8000]);
  });

  it("explains a 502 instead of calling it a server problem", () => {
    expect(errorMessage(502, "<html>Bad gateway</html>")).toMatch(/waking up/);
    expect(errorMessage(500, null)).toMatch(/server had a problem/);
  });
});

describe("waking banner", () => {
  it("shows while the backend wakes up, then the app loads normally", async () => {
    let calls = 0;
    let wake!: () => void;
    const awake = new Promise<void>((resolve) => (wake = resolve));
    mockApi({
      "GET /me": async () => {
        calls += 1;
        if (calls <= 2) return new Response("<html>502</html>", { status: 502 });
        await awake; // third try: the server is still starting up
        return json(meWith(profile));
      },
      "GET /drives": () => json([]),
    });
    renderApp("/", { retryDelay: () => 1 });

    expect(await screen.findByText(/Waking up the server/)).toBeInTheDocument();
    wake();
    expect(await screen.findByText(/No open drives right now/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(/Waking up the server/)).toBeNull());
    expect(calls).toBe(3);
  });

  it("doesn't retry a login POST; it explains and lets the user try again", async () => {
    let logins = 0;
    mockApi({
      "GET /me": () => json({ detail: "Not authenticated" }, 401),
      "POST /auth/login": () => {
        logins += 1;
        return new Response("bad gateway", { status: 502 });
      },
    });
    renderApp("/login");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "asha@example.com");
    await user.type(screen.getByLabelText("Password"), "whatever-pw");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/waking up/);
    expect(logins).toBe(1);
  });
});
