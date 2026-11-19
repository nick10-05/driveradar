import { readFileSync } from "node:fs";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The backend the dev proxy forwards to. Not exposed to the browser bundle (no VITE_ prefix).
const apiTarget = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";

// Same-origin API (DESIGN §7.3): the browser only talks to this origin, so the session
// cookie is first-party and no CORS is needed. Vercel does the same in prod (vercel.json).
// changeOrigin stays false: the browser's Origin header reaches FastAPI unchanged and
// must be in ALLOWED_ORIGINS for POST/PUT/PATCH (CSRF layer 2).
const proxy = {
  "/api": {
    target: apiTarget,
    rewrite: (path: string) => path.replace(/^\/api/, ""),
  },
};

// `npm run preview` serves the production build with the same security headers Vercel
// sends (read from vercel.json, one source of truth), so a CSP problem shows up locally.
type VercelConfig = { headers: { source: string; headers: { key: string; value: string }[] }[] };
const vercel = JSON.parse(readFileSync(new URL("./vercel.json", import.meta.url), "utf8")) as VercelConfig;
const prodHeaders = Object.fromEntries(
  (vercel.headers.find((rule) => rule.source === "/(.*)")?.headers ?? []).map((h) => [h.key, h.value]),
);
delete prodHeaders["Strict-Transport-Security"]; // meaningless (and sticky) on http://localhost

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true, // ALLOWED_ORIGINS lists http://localhost:5173 exactly
    proxy,
  },
  preview: {
    port: 5173,
    strictPort: true,
    proxy,
    headers: prodHeaders,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
    unstubGlobals: true,
  },
});
