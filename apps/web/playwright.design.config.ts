import { defineConfig, devices } from "@playwright/test";

// Seeded/mocked presentation checks need no database or model key.
const externalURL = process.env.DOTRIX_DESIGN_URL;
export default defineConfig({
  testDir: "./e2e",
  outputDir: "./.playwright-design-results",
  testMatch: ["astryx.spec.ts", "ui-review.spec.ts", "work-panel.spec.ts", "code-presentation.spec.ts"],
  workers: 1,
  timeout: 60_000,
  use: { baseURL: externalURL ?? "http://127.0.0.1:3102", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {},
      },
    },
  ],
  webServer: externalURL
    ? undefined
    : {
        command: "node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 3102",
        url: "http://127.0.0.1:3102",
        reuseExistingServer: !process.env.CI,
      },
});
