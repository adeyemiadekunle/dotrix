import { defineConfig, mergeConfig } from "vitest/config";

import viteConfig from "./vite.config";

// Unit tests for the web app's pure code; the browser tests are Playwright's (e2e/).
export default defineConfig((env) => mergeConfig(viteConfig(env), { test: { include: ["src/**/*.test.{ts,tsx}"] } }));
