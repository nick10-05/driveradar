/**
 * Times: the API stores and sends UTC (ISO 8601 with offset); students read IST
 * (CLAUDE.md). Formatting with an explicit timeZone makes the output the same on every
 * device, whatever its own clock zone is (a laptop set to UTC still shows IST).
 */
const IST = "Asia/Kolkata";

const deadlineFormat = new Intl.DateTimeFormat("en-IN", {
  timeZone: IST,
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
});

/** "20 Nov 2026, 5:00 pm IST" */
export function formatDeadlineIST(iso: string): string {
  return `${deadlineFormat.format(new Date(iso))} IST`;
}

/** "closes in 3 hours" / "closes in 2 days" / "closed". `now` is injectable for tests. */
export function timeLeft(iso: string, now: Date = new Date()): string {
  const ms = new Date(iso).getTime() - now.getTime();
  if (ms <= 0) return "deadline passed";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `closes in ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `closes in ${hours} hour${hours === 1 ? "" : "s"}`;
  return `closes in ${Math.floor(hours / 24)} days`;
}

/** True when less than 24 h are left (the card highlights it). */
export function isUrgent(iso: string, now: Date = new Date()): boolean {
  const ms = new Date(iso).getTime() - now.getTime();
  return ms > 0 && ms < 24 * 60 * 60 * 1000;
}

export function formatCtc(ctcText: string | null, ctcLpa: number | null): string | null {
  if (ctcText) return ctcText;
  if (ctcLpa !== null) return `${ctcLpa} LPA`;
  return null;
}
