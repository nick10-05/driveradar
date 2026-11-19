/**
 * Day 8: "Connect Telegram" on the profile page. The whole app renders; only `fetch` is
 * stubbed (the server and Telegram are never called).
 */
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, meWith, mockApi, profile, renderApp } from "./test/utils";

const branches = () => json([{ code: "CSE", name: "Computer Science" }]);
const LINK = {
  url: "https://t.me/DriveRadarBot?start=one-time-token",
  expires_at: "2099-01-01T10:15:00Z",
};
const linked = { ...profile, telegram_linked: true };

afterEach(() => {
  vi.useRealTimers();
});

describe("Telegram card", () => {
  it("is hidden when the server has no bot configured", async () => {
    mockApi({ "GET /me": () => json(meWith(profile)), "GET /branches": branches });
    renderApp("/profile");

    await screen.findByRole("heading", { name: "Your profile" });
    expect(screen.queryByRole("heading", { name: "Telegram alerts" })).toBeNull();
  });

  it("is hidden until a profile is saved (alerts need eligibility)", async () => {
    mockApi({ "GET /me": () => json(meWith(null, { telegram_available: true })), "GET /branches": branches });
    renderApp("/profile");

    await screen.findByRole("heading", { name: "Your profile" });
    expect(screen.queryByRole("heading", { name: "Telegram alerts" })).toBeNull();
  });

  it("gets a one-time link, opens it as a real link, then shows Connected once Start is pressed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let current = meWith(profile, { telegram_available: true });
    mockApi({
      "GET /me": () => json(current),
      "GET /branches": branches,
      "POST /me/telegram-link": () => json(LINK, 201),
    });
    renderApp("/profile");
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

    await user.click(await screen.findByRole("button", { name: "Connect Telegram" }));

    const open = await screen.findByRole("link", { name: "Open Telegram" });
    expect(open.getAttribute("href")).toBe(LINK.url);
    expect(open.getAttribute("rel")).toContain("noopener");
    expect(screen.getByRole("status").textContent).toContain("Waiting");

    // The student presses Start in Telegram; the page notices on its next poll of /me.
    current = meWith(linked, { telegram_available: true });
    await act(() => vi.advanceTimersByTimeAsync(4_500));

    expect(await screen.findByText(/^Connected\./)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Open Telegram" })).toBeNull();
  });

  it("stops waiting when the link expires and offers a new one", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const soon = { ...LINK, expires_at: new Date(Date.now() + 60_000).toISOString() };
    mockApi({
      "GET /me": () => json(meWith(profile, { telegram_available: true })),
      "GET /branches": branches,
      "POST /me/telegram-link": () => json(soon, 201),
    });
    renderApp("/profile");
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: "Connect Telegram" }));
    await screen.findByRole("link", { name: "Open Telegram" });

    await act(() => vi.advanceTimersByTimeAsync(61_000));

    expect(screen.getByText("That link expired. Get a new one.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Connect Telegram" })).toBeTruthy();
  });

  it("shows the server's error when a link can't be made", async () => {
    mockApi({
      "GET /me": () => json(meWith(profile, { telegram_available: true })),
      "GET /branches": branches,
      "POST /me/telegram-link": () => json({ detail: "Save your profile first" }, 409),
    });
    renderApp("/profile");

    await userEvent.setup().click(await screen.findByRole("button", { name: "Connect Telegram" }));

    expect((await screen.findByRole("alert")).textContent).toBe("Save your profile first");
  });

  it("disconnects", async () => {
    let current = meWith(linked, { telegram_available: true });
    const requests = mockApi({
      "GET /me": () => json(current),
      "GET /branches": branches,
      "DELETE /me/telegram-link": () => {
        current = meWith(profile, { telegram_available: true });
        return new Response(null, { status: 204 });
      },
    });
    renderApp("/profile");

    await userEvent.setup().click(await screen.findByRole("button", { name: "Disconnect Telegram" }));

    expect(await screen.findByRole("button", { name: "Connect Telegram" })).toBeTruthy();
    expect(requests.some((r) => r.method === "DELETE")).toBe(true);
  });

  it("keeps half-typed profile edits when Telegram gets linked", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let current = meWith(profile, { telegram_available: true });
    mockApi({
      "GET /me": () => json(current),
      "GET /branches": branches,
      "POST /me/telegram-link": () => json(LINK, 201),
    });
    renderApp("/profile");
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const cgpa = await screen.findByRole("spinbutton", { name: /CGPA/ });
    await user.clear(cgpa);
    await user.type(cgpa, "8.1");

    await user.click(screen.getByRole("button", { name: "Connect Telegram" }));
    await screen.findByRole("link", { name: "Open Telegram" });
    current = meWith(linked, { telegram_available: true });
    await act(() => vi.advanceTimersByTimeAsync(4_500));
    await screen.findByText(/^Connected\./);

    expect((screen.getByRole("spinbutton", { name: /CGPA/ }) as HTMLInputElement).value).toBe("8.1");
  });
});
