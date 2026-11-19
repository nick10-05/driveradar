import { describe, expect, it } from "vitest";

import { formatCtc, formatDeadlineIST, isUrgent, timeLeft } from "./format";

describe("formatDeadlineIST", () => {
  it("shows a UTC instant in IST (+05:30)", () => {
    // 11:30 UTC = 17:00 IST, the Day 3 example.
    const text = formatDeadlineIST("2026-11-20T11:30:00Z");
    expect(text).toMatch(/20 Nov 2026/);
    expect(text).toMatch(/5:00\s?pm/i);
    expect(text.endsWith("IST")).toBe(true);
  });

  it("rolls over to the next IST day", () => {
    // 20:00 UTC on the 20th is 01:30 on the 21st in India.
    expect(formatDeadlineIST("2026-11-20T20:00:00Z")).toMatch(/21 Nov 2026, 1:30\s?am/i);
  });
});

describe("timeLeft", () => {
  const now = new Date("2026-11-20T00:00:00Z");
  it.each([
    ["2026-11-20T00:30:00Z", "closes in 30 min"],
    ["2026-11-20T01:00:00Z", "closes in 1 hour"],
    ["2026-11-21T23:00:00Z", "closes in 47 hours"],
    ["2026-11-25T00:00:00Z", "closes in 5 days"],
    ["2026-11-20T00:00:00Z", "deadline passed"],
    ["2026-11-19T00:00:00Z", "deadline passed"],
  ])("%s → %s", (deadline, expected) => {
    expect(timeLeft(deadline, now)).toBe(expected);
  });

  it("flags the last 24 hours as urgent, not past or later ones", () => {
    expect(isUrgent("2026-11-20T23:59:00Z", now)).toBe(true);
    expect(isUrgent("2026-11-21T00:00:01Z", now)).toBe(false);
    expect(isUrgent("2026-11-19T23:59:00Z", now)).toBe(false);
  });
});

describe("formatCtc", () => {
  it("prefers the notice's own text, then the number, else nothing", () => {
    expect(formatCtc("6–8 LPA + bonus", 6)).toBe("6–8 LPA + bonus");
    expect(formatCtc(null, 12)).toBe("12 LPA");
    expect(formatCtc(null, 0)).toBe("0 LPA");
    expect(formatCtc(null, null)).toBeNull();
  });
});

describe("IST datetime-local helpers", () => {
  it("shows a UTC instant as IST wall-clock time for the input", async () => {
    const { toISTInput } = await import("./format");
    expect(toISTInput("2026-11-20T11:30:00Z")).toBe("2026-11-20T17:00");
    expect(toISTInput("2026-11-20T20:00:00Z")).toBe("2026-11-21T01:30"); // next IST day
    expect(toISTInput("2026-11-20T18:30:00Z")).toBe("2026-11-21T00:00"); // midnight, not 24:00
    expect(toISTInput(null)).toBe("");
  });

  it("sends the input back with an explicit +05:30 offset (round trip is exact)", async () => {
    const { fromISTInput, toISTInput } = await import("./format");
    expect(fromISTInput("2026-12-05T17:00")).toBe("2026-12-05T17:00:00+05:30");
    expect(new Date(fromISTInput("2026-12-05T17:00")!).toISOString()).toBe("2026-12-05T11:30:00.000Z");
    expect(toISTInput(fromISTInput("2026-12-05T17:00"))).toBe("2026-12-05T17:00");
    expect(fromISTInput("")).toBeNull();
    expect(fromISTInput("5 Dec")).toBeNull();
  });
});
