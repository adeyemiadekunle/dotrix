// End-to-end tests: the real web app against a real backend with a throwaway database and a
// deterministic model (apps/backend/scripts/e2e_server.py). Run with `pnpm --filter @pmagent/web e2e`.
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
      // A production build: what users run, and it can sit beside a `next dev` on :3000.
      command: "pnpm exec next build && pnpm exec next start --port 3100",
      url: `${WEB}/login`,
      timeout: 300_000,
      reuseExistingServer: !process.env.CI,
      env: { PMAGENT_API_URL: API },
    },
  ],
});
