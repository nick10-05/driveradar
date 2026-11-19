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

const istParts = new Intl.DateTimeFormat("en-CA", {
  timeZone: IST,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/**
 * UTC ISO → the "YYYY-MM-DDTHH:mm" an <input type="datetime-local"> holds, in IST.
 * (The input itself has no timezone; the admin always types IST wall-clock time.)
 */
export function toISTInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const parts = Object.fromEntries(
    istParts.formatToParts(new Date(iso)).map((p) => [p.type, p.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

/**
 * The input's IST wall-clock value → an ISO string with an explicit +05:30 offset, so the
 * server never has to guess (it would also read a naive time as IST, DESIGN §4.5).
 */
export function fromISTInput(value: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null;
  return `${value}:00+05:30`;
}
