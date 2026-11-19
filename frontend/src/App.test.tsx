/**
 * Screen flows (Day 6 "done when": a student logs in and sees their filtered feed).
 * The whole app renders; only `fetch` is stubbed.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Schemas } from "./api/client";
import { safeRedirect } from "./auth/RequireAuth";
import { drive, json, meWith, mockApi, profile, renderApp } from "./test/utils";

const location = () => screen.getByTestId("location").textContent;
const branches = () => json([{ code: "CSE", name: "Computer Science" }, { code: "ECE", name: "Electronics" }]);

const feed = [
  drive({ company: "Acme", eligible: true, apply_link: "https://acme.example/apply" }),
  drive({
    company: "Globex",
    eligible: false,
    apply_link: "https://globex.example/apply",
    reasons: ["Open to ECE only (you: CSE)", "Needs CGPA ≥ 8 (you: 7.5)"],
  }),
];

/** A tiny fake backend with a login state, so flows can log in and out. */
function fakeBackend(options: { me?: Schemas["MeOut"] | null; drives?: Schemas["StudentDriveOut"][] } = {}) {
  let me = options.me === undefined ? null : options.me;
  const requests = mockApi({
    "GET /me": () => (me ? json(me) : json({ detail: "Not logged in" }, 401)),
    "POST /auth/login": async (req) => {
      const body = (await req.json()) as { password: string };
      if (body.password !== "correct-horse") return json({ detail: "Invalid email or password" }, 401);
      me = meWith(profile);
      return json({ id: me.id, email: me.email, name: me.name, role: me.role });
    },
    "POST /auth/logout": () => {
      me = null;
      return new Response(null, { status: 204 });
    },
    "GET /drives": () => (me ? json(options.drives ?? feed) : json({ detail: "Not logged in" }, 401)),
    "GET /branches": branches,
  });
  return { requests, setMe: (value: Schemas["MeOut"] | null) => (me = value) };
}

describe("login → feed", () => {
  it("sends a logged-out visitor to the login page", async () => {
    fakeBackend();
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(location()).toBe("/login");
  });

  it("shows the server's message on a wrong password", async () => {
    fakeBackend();
    renderApp("/login");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "asha@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
    expect(location()).toBe("/login");
  });

  it("logs in and shows the filtered feed: eligible first, ineligible with reasons", async () => {
    const { requests } = fakeBackend();
    renderApp("/login");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "asha@example.com");
    await user.type(screen.getByLabelText("Password"), "correct-horse");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByRole("heading", { name: "Open drives" })).toBeInTheDocument();
    expect(location()).toBe("/");

    const [eligibleList, ineligibleList] = screen.getAllByRole("list").filter((l) => l.classList.contains("drive-list"));
    expect(within(eligibleList!).getByText("Acme")).toBeInTheDocument();
    expect(within(eligibleList!).getByRole("link", { name: /Apply/ })).toHaveAttribute("rel", "noopener noreferrer");

    const globex = within(ineligibleList!).getByText("Globex").closest("li")!;
    expect(within(globex).getByText("Open to ECE only (you: CSE)")).toBeInTheDocument();
    expect(within(globex).getByText("Needs CGPA ≥ 8 (you: 7.5)")).toBeInTheDocument();
    expect(within(globex).queryByRole("link", { name: /Apply/ })).toBeNull(); // no apply for ineligible

    const login = requests.find((r) => r.url.endsWith("/api/auth/login"))!;
    expect(await login.json()).toEqual({ email: "asha@example.com", password: "correct-horse" });
  });

  it("returns to the page they first asked for after logging in", async () => {
    fakeBackend();
    renderApp("/profile");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "asha@example.com");
    await user.type(screen.getByLabelText("Password"), "correct-horse");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("heading", { name: "Your profile" })).toBeInTheDocument();
    expect(location()).toBe("/profile");
  });

  it("shows an empty state when there are no open drives", async () => {
    fakeBackend({ me: meWith(profile), drives: [] });
    renderApp("/");
    expect(await screen.findByText(/No open drives right now/)).toBeInTheDocument();
  });

  it("shows deadlines in IST", async () => {
    fakeBackend({ me: meWith(profile), drives: [drive({ deadline: "2099-11-20T11:30:00Z" })] });
    renderApp("/");
    expect(await screen.findByText(/20 Nov 2099, 5:00\s?pm IST/i)).toBeInTheDocument();
  });
});

describe("session", () => {
  it("logs out, clears cached data and returns to login", async () => {
    const { requests } = fakeBackend({ me: meWith(profile) });
    const { queryClient } = renderApp("/");
    await screen.findByText("Acme");
    await userEvent.setup().click(screen.getByRole("button", { name: "Log out" }));
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(requests.some((r) => r.method === "POST" && r.url.endsWith("/api/auth/logout"))).toBe(true);
    expect(queryClient.getQueryData(["drives"])).toBeUndefined(); // next user sees nothing
  });

  it("goes to login when the session expires mid-use (401 on the feed)", async () => {
    const backend = fakeBackend({ me: meWith(profile) });
    const { queryClient } = renderApp("/");
    await screen.findByText("Acme");
    backend.setMe(null); // server-side session gone
    await queryClient.refetchQueries({ queryKey: ["drives"] });
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });

  it("shows a connection error instead of a blank page when the API is unreachable", async () => {
    mockApi({
      "GET /me": () => {
        throw new TypeError("Failed to fetch");
      },
    });
    renderApp("/");
    expect(await screen.findByRole("alert", {}, { timeout: 3000 })).toHaveTextContent(/Can't reach the server/);
  });
});

describe("profile", () => {
  it("sends a student without a profile to the form, saves numbers, then shows the feed", async () => {
    let saved: unknown;
    mockApi({
      "GET /me": () => json(meWith(saved ? profile : null)),
      "GET /branches": branches,
      "PUT /me/profile": async (req) => {
        saved = await req.json();
        return json(profile);
      },
      "GET /drives": () => json(feed),
    });
    renderApp("/");
    expect(await screen.findByText(/Fill this in once/)).toBeInTheDocument();
    expect(location()).toBe("/profile");

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Branch"), await screen.findByRole("option", { name: /Computer Science/ }));
    await user.type(screen.getByLabelText(/CGPA/), "7.5");
    await user.type(screen.getByLabelText("Graduation year"), "2027");
    await user.click(screen.getByRole("button", { name: "Save and see drives" }));

    expect(await screen.findByRole("heading", { name: "Open drives" })).toBeInTheDocument();
    expect(saved).toEqual({ branch_code: "CSE", cgpa: 7.5, active_backlogs: 0, grad_year: 2027 });
  });

  it("pre-fills an existing profile and refreshes the feed after saving", async () => {
    let drivesCalls = 0;
    mockApi({
      "GET /me": () => json(meWith(profile)),
      "GET /branches": branches,
      "PUT /me/profile": () => json({ ...profile, cgpa: 8.2 }),
      "GET /drives": () => {
        drivesCalls += 1;
        return json(feed);
      },
    });
    const { queryClient } = renderApp("/");
    await screen.findByText("Acme");
    expect(drivesCalls).toBe(1);

    const user = userEvent.setup();
    await user.click(screen.getByRole("link", { name: "Profile" }));
    const cgpa = await screen.findByLabelText(/CGPA/);
    expect(cgpa).toHaveValue(7.5);
    await waitFor(() => expect(screen.getByLabelText("Branch")).toHaveValue("CSE"));
    await user.clear(cgpa);
    await user.type(cgpa, "8.2");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Saved");
    // The feed was marked stale, so eligibility is recomputed by the server on next view.
    expect(queryClient.getQueryState(["drives"])?.isInvalidated).toBe(true);
  });

  it("shows the server's validation message", async () => {
    mockApi({
      "GET /me": () => json(meWith(profile)),
      "GET /branches": branches,
      "PUT /me/profile": () => json({ detail: "Unknown branch code" }, 422),
    });
    renderApp("/profile");
    const user = userEvent.setup();
    await screen.findByLabelText(/CGPA/);
    await waitFor(() => expect(screen.getByLabelText("Branch")).toHaveValue("CSE"));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unknown branch code");
  });
});

describe("register", () => {
  it("registers, logs in automatically and lands on the profile form", async () => {
    let me: Schemas["MeOut"] | null = null;
    const requests = mockApi({
      "GET /me": () => (me ? json(me) : json({ detail: "Not logged in" }, 401)),
      "POST /auth/register": () => json({ id: "x", email: "asha@example.com", name: "Asha", role: "student" }, 201),
      "POST /auth/login": () => {
        me = meWith(null);
        return json({ id: me.id, email: me.email, name: me.name, role: me.role });
      },
      "GET /branches": branches,
    });
    renderApp("/register");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Name"), "Asha");
    await user.type(screen.getByLabelText("Email"), "asha@example.com");
    await user.type(screen.getByLabelText(/Password/), "long-enough-pw");
    await user.type(screen.getByLabelText("Batch invite code"), "batch-2027");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText(/Fill this in once/)).toBeInTheDocument();
    expect(location()).toBe("/profile");
    const register = requests.find((r) => r.url.endsWith("/api/auth/register"))!;
    expect(await register.json()).toEqual({
      name: "Asha",
      email: "asha@example.com",
      password: "long-enough-pw",
      invite_code: "batch-2027",
    });
  });

  it("shows 'Invalid invite code' and doesn't try to log in", async () => {
    const requests = mockApi({
      "GET /me": () => json({ detail: "Not logged in" }, 401),
      "POST /auth/register": () => json({ detail: "Invalid invite code" }, 403),
    });
    renderApp("/register");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Name"), "Asha");
    await user.type(screen.getByLabelText("Email"), "asha@example.com");
    await user.type(screen.getByLabelText(/Password/), "long-enough-pw");
    await user.type(screen.getByLabelText("Batch invite code"), "wrong");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid invite code");
    expect(requests.some((r) => r.url.endsWith("/api/auth/login"))).toBe(false);
  });
});

describe("safeRedirect", () => {
  it.each([
    ["/profile", "/profile"],
    ["/", "/"],
    ["//evil.example", "/"],
    ["/\\evil.example", "/"],
    ["https://evil.example", "/"],
    [undefined, "/"],
    [42, "/"],
  ])("%s → %s", (from, expected) => {
    expect(safeRedirect(from)).toBe(expected);
  });
});
