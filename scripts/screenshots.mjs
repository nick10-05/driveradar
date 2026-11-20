// Take the README screenshots from a locally running app with demo data.
//
//   1. backend (fastapi dev, port 8000) with demo data: uv run python -m app.scripts.seed_demo
//      (start it with TELEGRAM_* set to fake values to show the Telegram card)
//   2. frontend production build: npm --prefix frontend run build && npm --prefix frontend run preview
//   3. node scripts/screenshots.mjs        -> docs/screenshots/*.png
//
// No dependencies: drives headless Microsoft Edge over the Chrome DevTools Protocol with
// Node's built-in fetch and WebSocket. Reads the demo password from backend/.env.demo and
// never prints it.

import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const APP = process.env.APP_URL ?? "http://localhost:5173";
const EDGE = process.env.EDGE_PATH ?? "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const OUT = join(ROOT, "docs", "screenshots");
const PORT = 9333;

const password = readFileSync(join(ROOT, "backend", ".env.demo"), "utf8")
  .split(/\r?\n/)
  .find((line) => line.startsWith("DEMO_PASSWORD="))
  ?.slice("DEMO_PASSWORD=".length);
if (!password) throw new Error("backend/.env.demo has no DEMO_PASSWORD");

const MOBILE = { width: 390, height: 844, deviceScaleFactor: 2, mobile: true };
const DESKTOP = { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false };
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const profileDir = mkdtempSync(join(tmpdir(), "driveradar-shots-"));
const edge = spawn(EDGE, [
  "--headless=new",
  `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${profileDir}`,
  "--no-first-run",
  "--hide-scrollbars",
  "about:blank",
]);

async function devtools() {
  for (let i = 0; i < 50; i++) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = targets.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch {
      // Edge not listening yet
    }
    await sleep(200);
  }
  throw new Error("Edge did not start");
}

function connect(url) {
  const ws = new WebSocket(url);
  let id = 0;
  const pending = new Map();
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    }
  };
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      pending.set(++id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  return new Promise((resolve) => (ws.onopen = () => resolve({ send, close: () => ws.close() })));
}

async function evaluate(cdp, expression) {
  const { result, exceptionDetails } = await cdp.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (exceptionDetails) throw new Error(exceptionDetails.text);
  return result.value;
}

/** Navigate, then wait until `text` is on the page (the data has loaded). */
async function open(cdp, path, text) {
  await cdp.send("Page.navigate", { url: APP + path });
  for (let i = 0; i < 100; i++) {
    await sleep(150);
    const found = await evaluate(cdp, `document.body?.innerText.includes(${JSON.stringify(text)})`).catch(() => false);
    if (found) return sleep(400); // let fonts/layout settle
  }
  throw new Error(`"${text}" never appeared on ${path}`);
}

async function shot(cdp, name, viewport, { fullPage = false } = {}) {
  await cdp.send("Emulation.setDeviceMetricsOverride", viewport);
  await sleep(300);
  let clip;
  if (fullPage) {
    const height = await evaluate(cdp, "document.documentElement.scrollHeight");
    clip = { x: 0, y: 0, width: viewport.width, height: Math.min(height, 2400), scale: 1 };
  }
  const { data } = await cdp.send("Page.captureScreenshot", {
    format: "png",
    ...(clip ? { clip, captureBeyondViewport: true } : {}),
  });
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, "base64"));
  console.log(`  ${name}.png`);
}

async function logIn(cdp, email) {
  await cdp.send("Page.navigate", { url: `${APP}/login` });
  await sleep(800);
  await evaluate(cdp, "fetch('/api/auth/logout', {method: 'POST'}).catch(() => {})");
  const status = await evaluate(
    cdp,
    `fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
       body: JSON.stringify({email: ${JSON.stringify(email)}, password: ${JSON.stringify(password)}})}).then(r => r.status)`,
  );
  if (status !== 200) throw new Error(`login as ${email} failed (${status})`);
}

async function driveId(cdp, company, admin = false) {
  const path = admin ? "/api/admin/drives" : "/api/drives";
  return evaluate(
    cdp,
    `fetch('${path}').then(r => r.json()).then(ds => ds.find(d => d.company === ${JSON.stringify(company)}).id)`,
  );
}

try {
  mkdirSync(OUT, { recursive: true });
  const cdp = await connect(await devtools());
  await cdp.send("Page.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", MOBILE);
  console.log(`Writing to ${OUT}`);

  await logIn(cdp, "asha.demo@example.com");
  await open(cdp, "/", "Zoho Corporation");
  await shot(cdp, "feed-mobile", MOBILE);
  await shot(cdp, "feed-desktop", DESKTOP, { fullPage: true });

  await cdp.send("Emulation.setDeviceMetricsOverride", MOBILE);
  const zoho = await driveId(cdp, "Zoho Corporation");
  await open(cdp, `/drives/${zoho}`, "Member Technical Staff");
  await shot(cdp, "drive-mobile", MOBILE, { fullPage: true });

  await open(cdp, "/tracker", "TCS Digital");
  await shot(cdp, "tracker-mobile", MOBILE, { fullPage: true });

  await open(cdp, "/profile", "Telegram alerts");
  await shot(cdp, "profile-telegram-mobile", MOBILE, { fullPage: true });

  await logIn(cdp, "ravi.demo@example.com");
  await open(cdp, "/", "Infosys");
  await evaluate(cdp, "document.querySelectorAll('details').forEach(d => d.open = true)");
  await shot(cdp, "feed-not-eligible-mobile", MOBILE, { fullPage: true });

  await logIn(cdp, "demo.admin@example.com");
  await cdp.send("Emulation.setDeviceMetricsOverride", DESKTOP);
  await open(cdp, "/admin", "Freshworks");
  await shot(cdp, "admin-list-desktop", DESKTOP);
  const freshworks = await driveId(cdp, "Freshworks", true);
  await open(cdp, `/admin/drives/${freshworks}`, "Software Engineer I");
  await shot(cdp, "admin-review-desktop", DESKTOP, { fullPage: true });

  cdp.close();
} finally {
  edge.kill();
  await sleep(500);
  rmSync(profileDir, { recursive: true, force: true, maxRetries: 5 });
}
