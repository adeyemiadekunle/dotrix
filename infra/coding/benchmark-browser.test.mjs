import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { BENCHMARK_SCENARIOS, runBenchmark, startFixtureServer, summarizeRuns } from "./benchmark-browser.mjs";

test("startFixtureServer serves all seven benchmark scenarios on loopback", async () => {
  const fixture = await startFixtureServer();
  try {
    assert.equal(BENCHMARK_SCENARIOS.length, 7);
    const checks = [
      ["/navigation", 200, "Workspace Home"],
      ["/login", 200, "Sign in"],
      ["/multi-step-form", 200, "Create Project"],
      ["/dynamic-loading", 200, "Loaded dynamically"],
      ["/responsive-layout", 200, "Desktop layout"],
      ["/error-handling", 500, "Simulated internal server error"],
      ["/permission-denied", 403, "Permission denied"],
    ];
    for (const [route, status, needle] of checks) {
      const res = await fetch(`${fixture.url}${route}`);
      assert.equal(res.status, status, route);
      assert.match(await res.text(), new RegExp(needle));
    }
  } finally {
    await fixture.close();
  }
});

test("summarizeRuns computes medians, percentiles, and flakiness without fabricating empty results", () => {
  assert.deepEqual(summarizeRuns([]), {
    runs: 0,
    success_count: 0,
    failure_count: 0,
    flakiness_rate: 0,
    median_ms: null,
    p95_ms: null,
    min_ms: null,
    max_ms: null,
    median_ttfi_ms: null,
    median_screenshot_bytes: null,
  });

  const stats = summarizeRuns([
    { ok: true, durationMs: 100, ttfiMs: 40, screenshotBytes: 1200 },
    { ok: true, durationMs: 200, ttfiMs: 50, screenshotBytes: 1400 },
    { ok: false, durationMs: 300, ttfiMs: 60, screenshotBytes: 1600 },
    { ok: true, durationMs: 400, ttfiMs: 70, screenshotBytes: 1800 },
  ]);
  assert.equal(stats.runs, 4);
  assert.equal(stats.success_count, 3);
  assert.equal(stats.failure_count, 1);
  assert.equal(stats.flakiness_rate, 0.25);
  assert.equal(stats.median_ms, 250);
  assert.equal(stats.p95_ms, 400);
  assert.equal(stats.min_ms, 100);
  assert.equal(stats.max_ms, 400);
  assert.equal(stats.median_ttfi_ms, 55);
  assert.equal(stats.median_screenshot_bytes, 1500);
});

test("runBenchmark reports missing binaries explicitly and aggregates mocked and CLI runs", async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "dotrix-bench-test-"));
  const fakeBin = path.join(tmp, "fake-ab.mjs");
  fs.writeFileSync(
    fakeBin,
    `#!/usr/bin/env node
import fs from "node:fs";
const args = process.argv.slice(2);
if (args[0] === "screenshot" && args[1]) fs.writeFileSync(args[1], "fake-png");
`,
    { mode: 0o755 },
  );

  try {
    const missing = await runBenchmark({
      runs: 2,
      engines: ["agent-browser"],
      agentBrowserBin: "/nonexistent/agent-browser",
    });
    assert.equal(missing.results[0].status, "not_installed");
    assert.equal(missing.results[0].summary.runs, 0);

    const mixed = await runBenchmark({
      runs: 3,
      engines: ["playwright", "agent-browser"],
      agentBrowserBin: fakeBin,
      runners: {
        playwright: async ({ runIndex }) => ({
          run: runIndex,
          ok: true,
          durationMs: 120 + runIndex * 10,
          ttfiMs: 35,
          screenshotBytes: 2048,
        }),
      },
    });
    const pw = mixed.results.find((r) => r.engine === "playwright");
    const ab = mixed.results.find((r) => r.engine === "agent-browser");
    assert.equal(pw.status, "completed");
    assert.equal(pw.summary.runs, 3);
    assert.equal(pw.summary.median_ms, 130);
    assert.equal(ab.status, "completed");
    assert.equal(ab.summary.runs, 3);
    assert.equal(ab.summary.success_count, 3);
    assert.equal(ab.summary.median_screenshot_bytes, 8);
    assert.equal(ab.interruption_recovery.interrupted, true);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
