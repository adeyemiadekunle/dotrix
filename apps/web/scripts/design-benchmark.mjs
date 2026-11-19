// Compare two built web apps on the same local network/CPU profile; never uses live accounts.
import { createServer } from "node:http";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve, sep, extname } from "node:path";
import { gzipSync } from "node:zlib";
import { createRequire } from "node:module";

const [before, after, output] = process.argv.slice(2);
if (!before || !after || !output) throw new Error("Usage: node apps/web/scripts/design-benchmark.mjs BEFORE_DIST AFTER_DIST OUTPUT_JSON");
const require = createRequire(import.meta.url);
const { chromium } = require("@playwright/test");
const types = {
  ".js": "application/javascript",
  ".css": "text/css",
  ".html": "text/html",
  ".json": "application/json",
  ".woff2": "font/woff2",
  ".svg": "image/svg+xml",
  ".wasm": "application/wasm",
};
async function serve(directory) {
  const root = resolve(directory),
    cache = new Map();
  const server = createServer((request, response) => {
    const url = new URL(request.url, "http://localhost");
    let path = resolve(root, `.${decodeURIComponent(url.pathname)}`);
    if (!path.startsWith(root + sep) && path !== root) {
      response.writeHead(403).end();
      return;
    }
    if (!extname(path) || path === root) path = resolve(root, "index.html");
    try {
      if (!cache.has(path)) {
        const content = readFileSync(path),
          type = types[extname(path)] ?? "application/octet-stream";
        const compressed = /javascript|text\/|json|svg/.test(type);
        cache.set(path, { body: compressed ? gzipSync(content) : content, type, compressed });
      }
      const { body, type, compressed } = cache.get(path);
      response
        .writeHead(200, {
          "Content-Type": type,
          "Content-Length": body.length,
          "Cache-Control": "no-store",
          ...(compressed ? { "Content-Encoding": "gzip" } : {}),
        })
        .end(body);
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  return { server, url: `http://127.0.0.1:${server.address().port}` };
}
const servers = { before: await serve(before), after: await serve(after) };
const browser = await chromium.launch(
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {},
);
const profile = {
  viewport: { width: 1440, height: 900 },
  latencyMs: 100,
  downloadBytesPerSecond: 200_000,
  uploadBytesPerSecond: 93_750,
  cpuSlowdown: 4,
  repetitions: 3,
};
const runs = [];
try {
  for (const path of ["/login", "/w/dotrix", "/w/dotrix/chat?new=1"]) {
    for (let repetition = 0; repetition < profile.repetitions; repetition++) {
      for (const label of ["before", "after"]) {
        const context = await browser.newContext({ viewport: profile.viewport, colorScheme: "light", reducedMotion: "reduce" });
        const page = await context.newPage();
        await page.route("**/v1/**", (route) => route.fulfill({ json: route.request().url().endsWith("/features") ? { organisations: true } : [] }));
        const cdp = await context.newCDPSession(page);
        await cdp.send("Network.enable");
        await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
        await cdp.send("Network.emulateNetworkConditions", {
          offline: false,
          latency: profile.latencyMs,
          downloadThroughput: profile.downloadBytesPerSecond,
          uploadThroughput: profile.uploadBytesPerSecond,
        });
        await cdp.send("Emulation.setCPUThrottlingRate", { rate: profile.cpuSlowdown });
        await page.addInitScript(() => {
          window.__dotrixLcp = 0;
          new PerformanceObserver((entries) => {
            window.__dotrixLcp = entries.getEntries().at(-1)?.startTime ?? 0;
          }).observe({ type: "largest-contentful-paint", buffered: true });
        });
        await page.goto(servers[label].url + path);
        if (path === "/login") await page.getByLabel("Password", { exact: true }).waitFor();
        else if (path.includes("chat")) await page.getByLabel("Message", { exact: true }).waitFor();
        else await page.getByRole("heading", { name: /Good/ }).waitFor();
        await page.evaluate(() => document.fonts.ready);
        const readyMs = await page.evaluate(() => performance.now());
        // Let the observer deliver the final paint after the ready target and fonts settle.
        await page.waitForTimeout(250);
        const metrics = await page.evaluate(() => ({
          lcpMs: window.__dotrixLcp,
          jsEncodedBytes: performance
            .getEntriesByType("resource")
            .filter((entry) => entry.name.endsWith(".js"))
            .reduce((total, entry) => total + entry.encodedBodySize, 0),
          jsResources: performance.getEntriesByType("resource").filter((entry) => entry.name.endsWith(".js")).length,
        }));
        runs.push({ path, repetition, label, readyMs, ...metrics });
        console.log(`${label} ${path} sample ${repetition + 1}: ready ${Math.round(readyMs)}ms, LCP ${Math.round(metrics.lcpMs)}ms`);
        await context.close();
      }
    }
  }
  const median = (values) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];
  const summary = Object.fromEntries(
    ["/login", "/w/dotrix", "/w/dotrix/chat?new=1"].map((path) => [
      path,
      Object.fromEntries(
        ["before", "after"].map((label) => {
          const rows = runs.filter((run) => run.path === path && run.label === label);
          return [
            label,
            Object.fromEntries(["readyMs", "lcpMs", "jsEncodedBytes", "jsResources"].map((metric) => [metric, median(rows.map((row) => row[metric]))])),
          ];
        }),
      ),
    ]),
  );
  writeFileSync(output, JSON.stringify({ profile, beforeDist: resolve(before), afterDist: resolve(after), summary, runs }, null, 2) + "\n");
} finally {
  await browser.close();
  await Promise.all(Object.values(servers).map(({ server }) => new Promise((done) => server.close(done))));
}
