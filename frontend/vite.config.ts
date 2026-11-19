import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The backend the dev proxy forwards to. Not exposed to the browser bundle (no VITE_ prefix).
const apiTarget = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true, // ALLOWED_ORIGINS lists http://localhost:5173 exactly
    proxy: {
      // Same-origin API (DESIGN §7.3): the browser only talks to localhost:5173, so the
      // session cookie is first-party and no CORS is needed. Vercel does the same on Day 7.
      // changeOrigin stays false: the browser's Origin header reaches FastAPI unchanged and
      // must be in ALLOWED_ORIGINS for POST/PUT/PATCH (CSRF layer 2).
      "/api": {
        target: apiTarget,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
    unstubGlobals: true,
  },
});
