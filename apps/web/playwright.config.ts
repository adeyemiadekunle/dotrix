// End-to-end tests: the real web app against a real backend with a throwaway database and a
// deterministic model (apps/backend/scripts/e2e_server.py). Run with `pnpm --filter @dotrix/web e2e`.
import { defineConfig, devices } from "@playwright/test";

const API = "http://127.0.0.1:8100";
const WEB = "http://localhost:3100";

export default defineConfig({
  testDir: "./e2e",
  // One shared backend and database: tests create their own users, but run one at a time.
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: WEB,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    {
      command: "uv run python ../backend/scripts/e2e_server.py",
      url: `${API}/health`,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: "pipe",
    },
    {
      // A production build: what users run, served beside a `vite` dev server on :3000, and
      // forwarding the API's paths to the test backend (vite.config.ts).
      command: "pnpm exec vite build && pnpm exec vite preview --port 3100",
      url: `${WEB}/login`,
      timeout: 300_000,
      reuseExistingServer: !process.env.CI,
      // Its own build folder, so a `vite build` for :3000 doesn't overwrite it mid-run.
      env: { DOTRIX_API_URL: API, DOTRIX_WEB_OUT_DIR: "dist-e2e" },
    },
  ],
});
