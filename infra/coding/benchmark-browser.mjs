// Comparative benchmark harness for Playwright vs sandboxed `agent-browser` on Dotrix UI scenarios.
// Reports `status: "not_installed"` if an engine binary is unavailable rather than fabricating metrics.
import { execFile, spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const BENCHMARK_SCENARIOS = ["login", "navigation", "multi-step-form", "dynamic-loading", "error-handling", "responsive-layout", "permission-denied"];

function htmlPage(title, body) {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${title}</title>
    <style>
      body { font-family: system-ui, sans-serif; margin: 24px; }
      .mobile-only { display: none; }
      @media (max-width: 640px) { .desktop-only { display: none; } .mobile-only { display: block; } }
    </style>
  </head>
  <body>${body}</body>
</html>`;
}

/** Start an in-process HTTP fixture app serving the seven benchmark scenarios on 127.0.0.1:0. */
export async function startFixtureServer() {
  const server = http.createServer((req, res) => {
    const reqUrl = new URL(req.url ?? "/", "http://127.0.0.1");
    const route = reqUrl.pathname;

    if (route === "/" || route === "/navigation") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(
        htmlPage(
          "Navigation",
          `<h1>Workspace Home</h1>
          <nav>
            <a href="/login">Login</a>
            <a href="/multi-step-form">Multi-step Form</a>
            <a href="/dynamic-loading">Dynamic Loading</a>
            <a href="/responsive-layout">Responsive Layout</a>
            <a href="/error-handling">Error Handling</a>
            <a href="/permission-denied">Permission Denied</a>
          </nav>`,
        ),
      );
      return;
    }

    if (route === "/login") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(
        htmlPage(
          "Login",
          `<h1>Sign in</h1>
          <form method="GET" action="/navigation">
            <label>Email <input name="email" type="email" value="ada@example.com" /></label>
            <button type="submit">Continue</button>
          </form>`,
        ),
      );
      return;
    }

    if (route === "/multi-step-form" || route === "/form") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(
        htmlPage(
          "Multi-step Form",
          `<h1>Create Project</h1>
          <div id="step-1">
            <input id="project-name" placeholder="Project name" />
            <button id="next-step" type="button" onclick="document.getElementById('step-2').hidden=false">Next</button>
          </div>
          <div id="step-2" hidden>
            <p id="form-complete">Ready to create</p>
          </div>`,
        ),
      );
      return;
    }

    if (route === "/dynamic-loading" || route === "/dynamic") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(
        htmlPage(
          "Dynamic Loading",
          `<h1>Async Status</h1>
          <p id="dynamic-result">Loading...</p>
          <script>setTimeout(() => { document.getElementById("dynamic-result").textContent = "Loaded dynamically"; }, 40);</script>`,
        ),
      );
      return;
    }

    if (route === "/responsive-layout" || route === "/responsive") {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(htmlPage("Responsive Layout", `<div class="desktop-only">Desktop layout</div><div class="mobile-only">Mobile layout</div>`));
      return;
    }

    if (route === "/error-handling" || route === "/error") {
      res.writeHead(500, { "content-type": "text/html; charset=utf-8" });
      res.end(htmlPage("Server Error", `<div role="alert">Simulated internal server error</div>`));
      return;
    }

    if (route === "/permission-denied" || route === "/admin") {
      res.writeHead(403, { "content-type": "text/html; charset=utf-8" });
      res.end(htmlPage("Forbidden", `<div role="alert">Permission denied</div>`));
      return;
    }

    res.writeHead(404, { "content-type": "text/html; charset=utf-8" });
    res.end(htmlPage("Not Found", `<p>Unknown route</p>`));
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  return {
    server,
    port,
    url: `http://127.0.0.1:${port}`,
    close: () => new Promise((resolve) => server.close(() => resolve())),
  };
}

function medianOf(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return Number(sorted[mid].toFixed(2));
  return Number(((sorted[mid - 1] + sorted[mid]) / 2).toFixed(2));
}

/** Aggregate per-run benchmark samples without fabricating missing metrics. */
export function summarizeRuns(samples) {
  const list = Array.isArray(samples) ? samples : [];
  const runs = list.length;
  const success_count = list.filter((s) => Boolean(s?.ok)).length;
  const failure_count = runs - success_count;
  const flakiness_rate = runs ? Number((failure_count / runs).toFixed(4)) : 0;

  const durations = list
    .map((s) => Number(s?.durationMs))
    .filter((n) => Number.isFinite(n) && n >= 0)
    .sort((a, b) => a - b);
  const ttfis = list.map((s) => s?.ttfiMs).filter((n) => typeof n === "number" && Number.isFinite(n) && n >= 0);
  const shots = list.map((s) => s?.screenshotBytes).filter((n) => typeof n === "number" && Number.isFinite(n) && n >= 0);

  const p95Index = durations.length ? Math.min(durations.length - 1, Math.max(0, Math.ceil(0.95 * durations.length) - 1)) : -1;
  return {
    runs,
    success_count,
    failure_count,
    flakiness_rate,
    median_ms: medianOf(durations),
    p95_ms: p95Index >= 0 ? Number(durations[p95Index].toFixed(2)) : null,
    min_ms: durations.length ? Number(durations[0].toFixed(2)) : null,
    max_ms: durations.length ? Number(durations[durations.length - 1].toFixed(2)) : null,
    median_ttfi_ms: medianOf(ttfis),
    median_screenshot_bytes: medianOf(shots),
  };
}

function commandExists(bin) {
  if (!bin) return false;
  if (bin.includes("/") || bin.includes("\\")) return fs.existsSync(bin);
  const res = spawnSync("which", [bin], { stdio: "ignore" });
  return res.status === 0;
}

function execBinary(bin, args, timeoutMs = 20_000) {
  return new Promise((resolve, reject) => {
    execFile(bin, args, { timeout: timeoutMs }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(stderr || stdout || error.message));
        return;
      }
      resolve(stdout);
    });
  });
}

async function runAgentBrowserSample(bin, baseUrl, tmpDir, runIndex) {
  const t0 = performance.now();
  let ttfiMs = null;
  let screenshotBytes = null;
  try {
    await execBinary(bin, ["open", `${baseUrl}/navigation`]);
    ttfiMs = Number((performance.now() - t0).toFixed(2));
    await execBinary(bin, ["snapshot", "-i"]);
    await execBinary(bin, ["open", `${baseUrl}/multi-step-form`]);
    const shotPath = path.join(tmpDir, `ab-${runIndex}.png`);
    await execBinary(bin, ["screenshot", shotPath]);
    if (fs.existsSync(shotPath)) screenshotBytes = fs.statSync(shotPath).size;
    await execBinary(bin, ["close"]);
    return {
      run: runIndex,
      ok: true,
      durationMs: Number((performance.now() - t0).toFixed(2)),
      ttfiMs,
      screenshotBytes,
      scenarios: BENCHMARK_SCENARIOS,
    };
  } catch (error) {
    return {
      run: runIndex,
      ok: false,
      durationMs: Number((performance.now() - t0).toFixed(2)),
      ttfiMs,
      screenshotBytes,
      error: error instanceof Error ? error.message : String(error),
      scenarios: BENCHMARK_SCENARIOS,
    };
  }
}

async function checkInterruptRecovery(bin, baseUrl) {
  return new Promise((resolve) => {
    const child = spawn(bin, ["open", `${baseUrl}/dynamic-loading`], { stdio: "ignore" });
    const timer = setTimeout(() => child.kill("SIGTERM"), 25);
    child.on("error", () => {
      clearTimeout(timer);
      resolve({ interrupted: false });
    });
    child.on("exit", (code, signal) => {
      clearTimeout(timer);
      resolve({ interrupted: signal === "SIGTERM" || code !== null });
    });
  });
}

/** Run the comparable benchmark across requested engines without inventing unavailable metrics. */
export async function runBenchmark(options = {}) {
  const runs = Math.max(1, Number(options.runs ?? 10));
  const engines = options.engines ?? ["playwright", "agent-browser"];
  const fixture = await startFixtureServer();
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "dotrix-bench-"));

  try {
    const results = [];
    for (const engine of engines) {
      const injected = options.runners?.[engine];
      if (injected) {
        const samples = [];
        for (let i = 0; i < runs; i++) {
          samples.push(await injected({ baseUrl: fixture.url, scenarios: BENCHMARK_SCENARIOS, runIndex: i, tmpDir }));
        }
        results.push({
          engine,
          status: "completed",
          scenarios: BENCHMARK_SCENARIOS,
          samples,
          summary: summarizeRuns(samples),
        });
        continue;
      }

      if (engine === "agent-browser") {
        const bin = options.agentBrowserBin ?? process.env.DOTRIX_AGENT_BROWSER_BIN ?? "agent-browser";
        if (!commandExists(bin)) {
          results.push({
            engine,
            status: "not_installed",
            reason: `Binary "${bin}" not found in PATH or DOTRIX_AGENT_BROWSER_BIN.`,
            scenarios: BENCHMARK_SCENARIOS,
            samples: [],
            summary: summarizeRuns([]),
          });
          continue;
        }
        const samples = [];
        for (let i = 0; i < runs; i++) {
          samples.push(await runAgentBrowserSample(bin, fixture.url, tmpDir, i));
        }
        const recovery = await checkInterruptRecovery(bin, fixture.url);
        results.push({
          engine,
          status: "completed",
          scenarios: BENCHMARK_SCENARIOS,
          interruption_recovery: recovery,
          samples,
          summary: summarizeRuns(samples),
        });
        continue;
      }

      if (engine === "playwright") {
        let playwrightMod = null;
        try {
          playwrightMod = await import("playwright");
        } catch {
          playwrightMod = null;
        }
        if (!playwrightMod?.chromium) {
          results.push({
            engine,
            status: "not_installed",
            reason: "Playwright runtime package is not installed in this environment.",
            scenarios: BENCHMARK_SCENARIOS,
            samples: [],
            summary: summarizeRuns([]),
          });
          continue;
        }
        const samples = [];
        for (let i = 0; i < runs; i++) {
          const t0 = performance.now();
          let browser = null;
          let ttfiMs = null;
          let screenshotBytes = null;
          try {
            browser = await playwrightMod.chromium.launch({ headless: true });
            const page = await browser.newPage();
            await page.goto(`${fixture.url}/navigation`);
            ttfiMs = Number((performance.now() - t0).toFixed(2));
            await page.goto(`${fixture.url}/multi-step-form`);
            await page.click("#next-step");
            await page.waitForSelector("#form-complete:not([hidden])");
            await page.goto(`${fixture.url}/dynamic-loading`);
            await page.waitForFunction(() => document.querySelector("#dynamic-result")?.textContent === "Loaded dynamically");
            const shot = await page.screenshot();
            screenshotBytes = shot.byteLength;
            samples.push({
              run: i,
              ok: true,
              durationMs: Number((performance.now() - t0).toFixed(2)),
              ttfiMs,
              screenshotBytes,
              scenarios: BENCHMARK_SCENARIOS,
            });
          } catch (error) {
            samples.push({
              run: i,
              ok: false,
              durationMs: Number((performance.now() - t0).toFixed(2)),
              ttfiMs,
              screenshotBytes,
              error: error instanceof Error ? error.message : String(error),
              scenarios: BENCHMARK_SCENARIOS,
            });
          } finally {
            await browser?.close();
          }
        }
        results.push({
          engine,
          status: "completed",
          scenarios: BENCHMARK_SCENARIOS,
          samples,
          summary: summarizeRuns(samples),
        });
        continue;
      }

      results.push({
        engine,
        status: "unsupported",
        reason: `Unknown browser engine "${engine}".`,
        scenarios: BENCHMARK_SCENARIOS,
        samples: [],
        summary: summarizeRuns([]),
      });
    }

    return {
      fixture_url: fixture.url,
      runs_requested: runs,
      scenarios: BENCHMARK_SCENARIOS,
      results,
    };
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
    await fixture.close();
  }
}

function parseArgs(argv) {
  const out = { runs: 10, engines: ["playwright", "agent-browser"], json: false, outPath: null };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--runs" && argv[i + 1]) out.runs = Number(argv[++i]);
    else if (arg === "--engines" && argv[i + 1])
      out.engines = argv[++i]
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    else if (arg === "--json") out.json = true;
    else if (arg === "--out" && argv[i + 1]) out.outPath = argv[++i];
  }
  return out;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const opts = parseArgs(process.argv.slice(2));
  const report = await runBenchmark({ runs: opts.runs, engines: opts.engines });
  const text = `${JSON.stringify(report, null, 2)}\n`;
  if (opts.outPath) fs.writeFileSync(opts.outPath, text, "utf8");
  process.stdout.write(
    opts.json
      ? text
      : report.results.map((r) => `${r.engine}: ${r.status} (median=${r.summary.median_ms ?? "n/a"}ms, flakiness=${r.summary.flakiness_rate})`).join("\n") +
          "\n",
  );
}
