/**
 * Day 7 screens: drive page + tracker (student) and paste → extract → review → save →
 * publish (admin). The whole app renders; only `fetch` is stubbed.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Schemas } from "./api/client";
import { drive, json, meWith, mockApi, profile, renderApp } from "./test/utils";

const location = () => screen.getByTestId("location").textContent;
const DRIVE_ID = "22222222-2222-2222-2222-222222222222";
const branches = () => json([{ code: "CSE", name: "Computer Science" }, { code: "ECE", name: "Electronics" }]);

type Detail = Schemas["StudentDriveDetailOut"];
type Application = Schemas["ApplicationOut"];

function detail(overrides: Partial<Detail> = {}): Detail {
  return {
    ...drive({ id: DRIVE_ID, company: "Acme" }),
    raw_text: "Acme is hiring. CSE only.",
    application: null,
    next_statuses: ["interested", "applied"],
    ...overrides,
  };
}

function application(status: Application["status"], next: Application["next_statuses"]): Application {
  return {
    id: "a1",
    drive_id: DRIVE_ID,
    status,
    notes: null,
    updated_at: "2026-11-19T10:00:00Z",
    timeline: [{ from_status: null, to_status: status, at: "2026-11-19T10:00:00Z" }],
    next_statuses: next,
  };
}

describe("drive page", () => {
  it("starts tracking with the moves the server offers, then shows the new ones", async () => {
    let current = detail();
    const requests = mockApi({
      "GET /me": () => json(meWith(profile)),
      [`GET /drives/${DRIVE_ID}`]: () => json(current),
      [`PUT /drives/${DRIVE_ID}/application`]: () => {
        const app = application("applied", ["test", "interview", "rejected", "withdrawn"]);
        current = detail({ application: app, next_statuses: app.next_statuses });
        return json(app);
      },
      "GET /me/applications": () => json([]),
    });
    renderApp(`/drives/${DRIVE_ID}`);

    const group = await screen.findByRole("group", { name: "Update status" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual(["I'm interested", "I applied"]);

    await userEvent.setup().click(within(group).getByRole("button", { name: "I applied" }));

    await waitFor(() =>
      expect(within(screen.getByRole("group", { name: "Update status" })).getAllByRole("button")).toHaveLength(4),
    );
    expect(screen.getByText("Applied", { selector: ".status-badge" })).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Timeline" })).getByText(/started tracking/)).toBeInTheDocument();
    const put = requests.find((r) => r.method === "PUT")!;
    expect(await put.json()).toEqual({ status: "applied" });
  });

  it("shows no buttons in a final state", async () => {
    mockApi({
      "GET /me": () => json(meWith(profile)),
      [`GET /drives/${DRIVE_ID}`]: () => json(detail({ application: application("offer", []), next_statuses: [] })),
    });
    renderApp(`/drives/${DRIVE_ID}`);
    expect(await screen.findByText("Offer", { selector: ".status-badge" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Update status" })).toBeNull();
  });

  it("asks before a move that can't be undone, and sends nothing if cancelled", async () => {
    const requests = mockApi({
      "GET /me": () => json(meWith(profile)),
      [`GET /drives/${DRIVE_ID}`]: () =>
        json(detail({ application: application("interested", ["applied", "withdrawn"]), next_statuses: ["applied", "withdrawn"] })),
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderApp(`/drives/${DRIVE_ID}`);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Withdraw" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/can't be undone/));
    expect(requests.some((r) => r.method === "PUT")).toBe(false);
  });

  it("shows the server's 409 message when a move is refused", async () => {
    mockApi({
      "GET /me": () => json(meWith(profile)),
      [`GET /drives/${DRIVE_ID}`]: () => json(detail()),
      [`PUT /drives/${DRIVE_ID}/application`]: () => json({ detail: "Can't move from offer to applied" }, 409),
      "GET /me/applications": () => json([]),
    });
    renderApp(`/drives/${DRIVE_ID}`);
    await userEvent.setup().click(await screen.findByRole("button", { name: "I applied" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Can't move from offer to applied");
  });

  it("saves notes as a same-status update", async () => {
    const requests = mockApi({
      "GET /me": () => json(meWith(profile)),
      [`GET /drives/${DRIVE_ID}`]: () =>
        json(detail({ application: application("applied", ["test"]), next_statuses: ["test"] })),
      [`PUT /drives/${DRIVE_ID}/application`]: () => json(application("applied", ["test"])),
      "GET /me/applications": () => json([]),
    });
    renderApp(`/drives/${DRIVE_ID}`);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/Notes/), "  Aptitude on Monday ");
    await user.click(screen.getByRole("button", { name: "Save notes" }));
    await waitFor(() => expect(requests.some((r) => r.method === "PUT")).toBe(true));
    expect(await requests.find((r) => r.method === "PUT")!.json()).toEqual({
      status: "applied",
      notes: "Aptitude on Monday",
    });
  });

  it("renders the notice as text, never as HTML", async () => {
    mockApi({
      "GET /me": () => json(meWith(profile)),
      [`GET /drives/${DRIVE_ID}`]: () => json(detail({ raw_text: 'Apply now <img src=x onerror="alert(1)">' })),
    });
    const { container } = renderApp(`/drives/${DRIVE_ID}`);
    expect(await screen.findByText(/<img src=x onerror/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("says so for a drive that doesn't exist (or is a draft)", async () => {
    mockApi({
      "GET /me": () => json(meWith(profile)),
      [`GET /drives/${DRIVE_ID}`]: () => json({ detail: "Drive not found" }, 404),
    });
    renderApp(`/drives/${DRIVE_ID}`);
    expect(await screen.findByRole("alert")).toHaveTextContent("This drive doesn't exist.");
  });

  it("is reachable from the feed", async () => {
    mockApi({
      "GET /me": () => json(meWith(profile)),
      "GET /drives": () => json([drive({ id: DRIVE_ID, company: "Acme" })]),
      [`GET /drives/${DRIVE_ID}`]: () => json(detail()),
    });
    renderApp("/");
    await userEvent.setup().click(await screen.findByRole("link", { name: "Acme" }));
    expect(await screen.findByRole("heading", { name: "Original notice" })).toBeInTheDocument();
    expect(location()).toBe(`/drives/${DRIVE_ID}`);
  });
});

describe("tracker", () => {
  it("lists my drives with status, drive state and timeline", async () => {
    mockApi({
      "GET /me": () => json(meWith(profile)),
      "GET /me/applications": () =>
        json([
          {
            ...application("interview", ["offer", "rejected", "withdrawn"]),
            notes: "HR round next",
            drive: { id: DRIVE_ID, company: "Acme", role_title: "SDE", deadline: "2026-11-01T11:30:00Z", state: "expired" },
          },
        ]),
    });
    renderApp("/tracker");
    const card = (await screen.findByRole("link", { name: "Acme" })).closest("li")!;
    expect(within(card).getByText("Interview", { selector: ".status-badge" })).toBeInTheDocument();
    expect(within(card).getByText(/Deadline passed/)).toBeInTheDocument(); // history stays visible
    expect(within(card).getByText(/HR round next/)).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Acme" })).toHaveAttribute("href", `/drives/${DRIVE_ID}`);
  });

  it("has a helpful empty state", async () => {
    mockApi({ "GET /me": () => json(meWith(profile)), "GET /me/applications": () => json([]) });
    renderApp("/tracker");
    expect(await screen.findByText(/Nothing tracked yet/)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------- admin

const admin = { ...meWith(null), role: "admin" };

function adminDrive(overrides: Partial<Schemas["AdminDriveOut"]> = {}): Schemas["AdminDriveOut"] {
  return {
    ...drive({ id: DRIVE_ID, company: "Acme", deadline: "2026-12-05T11:30:00Z" }),
    state: "draft",
    status: "draft",
    source: null,
    raw_text: "Acme notice",
    extraction_run_id: null,
    closed_at: null,
    created_at: "2026-11-19T10:00:00Z",
    updated_at: "2026-11-19T10:00:00Z",
    ...overrides,
  } as Schemas["AdminDriveOut"];
}

describe("admin", () => {
  it("keeps students out of admin pages (the server returns 403 anyway)", async () => {
    mockApi({ "GET /me": () => json(meWith(profile)), "GET /drives": () => json([]) });
    renderApp("/admin");
    await screen.findByRole("heading", { name: "Open drives" });
    expect(location()).toBe("/");
    expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
  });

  it("paste → extract → review flagged fields → save draft", async () => {
    const extracted: Schemas["ExtractOut"] = {
      extraction_run_id: "33333333-3333-3333-3333-333333333333",
      status: "ok",
      provider: "openai_compatible",
      model: "some-model",
      draft: {
        company: "Acme",
        role_title: "SDE",
        ctc_text: null,
        ctc_lpa: null,
        location: null,
        apply_link: null,
        deadline: "2026-12-05T11:30:00Z",
        eligibility: { min_cgpa: 7.5, max_active_backlogs: null, grad_years: [], allowed_branches: ["CSE"] },
      },
      issues: [{ field: "eligibility.min_cgpa", kind: "verify", message: "The quoted text doesn't contain this value; check it." }],
    };
    let created: unknown;
    const requests = mockApi({
      "GET /me": () => json(admin),
      "GET /branches": branches,
      "POST /admin/drives/extract": () => json(extracted),
      "POST /admin/drives": async (req) => {
        created = await req.json();
        return json(adminDrive({ extraction_run_id: extracted.extraction_run_id }), 201);
      },
      [`GET /admin/drives/${DRIVE_ID}`]: () => json(adminDrive()),
      "GET /admin/drives": () => json([]),
    });
    renderApp("/admin/new");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/Paste the notice/), "Acme hiring SDE. CGPA 7. Apply by 5 Dec 5pm.");
    await user.click(screen.getByRole("button", { name: "Extract with AI" }));

    expect(await screen.findByRole("status")).toHaveTextContent(/1 field\(s\) flagged/);
    expect(screen.getByLabelText("Company")).toHaveValue("Acme");
    expect(screen.getByLabelText(/Deadline/)).toHaveValue("2026-12-05T17:00"); // IST, not UTC
    // The flag sits next to the field it's about.
    const cgpaField = screen.getByLabelText("Minimum CGPA").closest(".field")!;
    expect(within(cgpaField as HTMLElement).getByText(/doesn't contain this value/)).toBeInTheDocument();
    // The admin corrects it.
    await user.clear(screen.getByLabelText("Minimum CGPA"));
    await user.type(screen.getByLabelText("Minimum CGPA"), "7");
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "CSE" })).toBeChecked());
    await user.click(screen.getByRole("button", { name: "Save as draft" }));

    await waitFor(() => expect(location()).toBe(`/admin/drives/${DRIVE_ID}`));
    expect(created).toMatchObject({
      company: "Acme",
      role_title: "SDE",
      deadline: "2026-12-05T17:00:00+05:30",
      raw_text: "Acme hiring SDE. CGPA 7. Apply by 5 Dec 5pm.",
      extraction_run_id: extracted.extraction_run_id, // links the drive to its audit row
      eligibility: { min_cgpa: 7, allowed_branches: ["CSE"] },
    });
    expect(requests.filter((r) => r.method === "PATCH")).toHaveLength(0); // saved, not published
  });

  it("falls back to manual entry when extraction is off", async () => {
    mockApi({
      "GET /me": () => json(admin),
      "GET /branches": branches,
      "POST /admin/drives/extract": () =>
        json({
          extraction_run_id: "44444444-4444-4444-4444-444444444444",
          status: "disabled",
          provider: "none",
          model: null,
          draft: { company: null, role_title: null, ctc_text: null, ctc_lpa: null, location: null, apply_link: null, deadline: null, eligibility: { min_cgpa: null, max_active_backlogs: null, grad_years: [], allowed_branches: [] } },
          issues: [],
        }),
    });
    renderApp("/admin/new");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/Paste the notice/), "Some notice");
    await user.click(screen.getByRole("button", { name: "Extract with AI" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/AI extraction is off/);
    expect(screen.getByLabelText("Company")).toHaveValue("");
    // Client-side check: missing required fields are listed, nothing is sent.
    await user.click(screen.getByRole("button", { name: "Save as draft" }));
    expect(await screen.findAllByText("Required.")).toHaveLength(2);
  });

  it("publishes a draft after confirming", async () => {
    let current = adminDrive();
    const requests = mockApi({
      "GET /me": () => json(admin),
      "GET /branches": branches,
      [`GET /admin/drives/${DRIVE_ID}`]: () => json(current),
      [`PATCH /admin/drives/${DRIVE_ID}`]: () => {
        current = adminDrive({ status: "published", state: "open", updated_at: "2026-11-19T11:00:00Z" });
        return json(current);
      },
      "GET /admin/drives": () => json([current]),
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderApp(`/admin/drives/${DRIVE_ID}`);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Publish" }));
    expect(await screen.findByRole("button", { name: "Close drive" })).toBeInTheDocument();
    expect(await requests.find((r) => r.method === "PATCH")!.json()).toEqual({ status: "published" });
  });
});
