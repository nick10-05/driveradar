import { describe, expect, it } from "vitest";

import { json, mockApi } from "../test/utils";
import { ApiError, api, errorMessage, unwrap } from "./client";

describe("errorMessage", () => {
  it("uses FastAPI's string detail", () => {
    expect(errorMessage(401, { detail: "Invalid email or password" })).toBe(
      "Invalid email or password",
    );
  });

  it("names the fields in a 422 validation list, without the 'body' prefix", () => {
    const body = {
      detail: [
        { loc: ["body", "cgpa"], msg: "Input should be less than or equal to 10" },
        { loc: ["body", "grad_year"], msg: "Field required" },
      ],
    };
    expect(errorMessage(422, body)).toBe(
      "cgpa: Input should be less than or equal to 10; grad_year: Field required",
    );
  });

  it("falls back to a friendly message by status", () => {
    expect(errorMessage(429, null)).toMatch(/Too many attempts/);
    expect(errorMessage(502, "<html>Bad gateway</html>")).toMatch(/server had a problem/);
    expect(errorMessage(418, {})).toBe("Request failed (418)");
  });
});

describe("api + unwrap", () => {
  it("calls the same-origin /api prefix and returns the data", async () => {
    const requests = mockApi({ "GET /branches": () => json([{ code: "CSE", name: "Computer" }]) });
    const branches = await unwrap(api.GET("/branches"));
    expect(branches).toEqual([{ code: "CSE", name: "Computer" }]);
    const url = new URL(requests[0]!.url);
    expect(url.origin).toBe(window.location.origin); // same origin: cookie is first-party
    expect(url.pathname).toBe("/api/branches");
  });

  it("throws ApiError with status and message on non-2xx", async () => {
    mockApi({ "POST /auth/login": () => json({ detail: "Invalid email or password" }, 401) });
    const error = await unwrap(
      api.POST("/auth/login", { body: { email: "a@b.co", password: "x" } }),
    ).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 401, message: "Invalid email or password" });
  });

  it("sends JSON bodies for unsafe methods", async () => {
    const requests = mockApi({ "PUT /me/profile": () => json({}) });
    await unwrap(
      api.PUT("/me/profile", {
        body: { branch_code: "CSE", cgpa: 7.5, active_backlogs: 0, grad_year: 2027 },
      }),
    );
    const sent = requests[0]!;
    expect(sent.method).toBe("PUT");
    expect(sent.headers.get("content-type")).toMatch(/application\/json/);
    expect(await sent.json()).toEqual({
      branch_code: "CSE",
      cgpa: 7.5, // a number, not "7.5"
      active_backlogs: 0,
      grad_year: 2027,
    });
  });
});
