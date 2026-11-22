import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createInterface } from "node:readline";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { BROWSER_TOOLS, validateRef, validateScreenshotPath, validateUrl } from "./agent-browser-mcp.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ADAPTER = path.join(HERE, "agent-browser-mcp.mjs");

test("validateUrl allows loopback and allowlisted hosts while blocking metadata, private networks, credentials, and unsafe schemes", () => {
  assert.equal(validateUrl("http://localhost:3000/login"), "http://localhost:3000/login");
  assert.equal(validateUrl("http://127.0.0.1:8080/"), "http://127.0.0.1:8080/");
  assert.equal(validateUrl("http://[::1]:5173/app"), "http://[::1]:5173/app");
  assert.equal(validateUrl("https://staging.example.com/ok", ["staging.example.com"]), "https://staging.example.com/ok");

  for (const blocked of [
    "http://169.254.169.254/latest/meta-data/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://100.100.100.200/latest/meta-data",
    "http://[fd00:ec2::254]/",
    "http://[::ffff:169.254.169.254]/",
    "http://10.0.0.1/",
    "http://172.16.5.4/",
    "http://192.168.1.10/",
    "http://100.64.1.1/",
    "http://user:secret@localhost:3000/",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "https://example.com/",
  ]) {
    assert.throws(() => validateUrl(blocked), `Expected ${blocked} to be rejected`);
  }

  // Metadata/private IPs remain blocked even if accidentally added to allowedHosts.
  assert.throws(() => validateUrl("http://169.254.169.254/", ["169.254.169.254"]));
  assert.throws(() => validateUrl("http://10.0.0.8/", ["10.0.0.8"]));
});

test("validateScreenshotPath confines single-segment PNG filenames to outputDir", () => {
  const dir = "/tmp/playwright-test";
  assert.equal(validateScreenshotPath("proof.png", dir), path.resolve(dir, "proof.png"));
  assert.equal(validateScreenshotPath("step-1_ok.PNG", dir), path.resolve(dir, "step-1_ok.PNG"));
  for (const bad of ["../escape.png", "/tmp/escape.png", "nested/proof.png", "a\\b.png", "proof.jpg", ".png", ""]) {
    assert.throws(() => validateScreenshotPath(bad, dir), `Expected ${bad} to be rejected`);
  }
});

test("validateRef enforces bounded non-control strings", () => {
  assert.equal(validateRef("@e12"), "@e12");
  assert.throws(() => validateRef(""));
  assert.throws(() => validateRef("bad\nref"));
  assert.throws(() => validateRef("x".repeat(300)));
});

function withMcpClient(envOverrides, callback) {
  return new Promise((resolve, reject) => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "dotrix-ab-test-"));
    const outDir = path.join(tmp, "screenshots");
    const logPath = path.join(tmp, "calls.log");
    const fakeBin = path.join(tmp, "fake-agent-browser.mjs");
    fs.writeFileSync(
      fakeBin,
      `#!/usr/bin/env node
import fs from "node:fs";
const args = process.argv.slice(2);
fs.appendFileSync(${JSON.stringify(logPath)}, JSON.stringify(args) + "\\n");
if (args[1] === "http://127.0.0.1:9999/crash") {
  process.stderr.write("browser process crashed\\n");
  process.exit(2);
}
if (args[1] === "http://127.0.0.1:9999/hang") {
  setTimeout(() => process.exit(0), 10000);
} else {
  if (args[0] === "screenshot" && args[1]) {
    fs.writeFileSync(args[1], "png-bytes");
  }
  process.stdout.write("ran:" + args.join(" ") + "\\n");
}
`,
      { mode: 0o755 },
    );

    const child = spawn(process.execPath, [ADAPTER, "--output-dir", outDir], {
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, DOTRIX_AGENT_BROWSER_BIN: fakeBin, DOTRIX_BROWSER_EVENTS: "1", ...envOverrides },
    });

    const pending = new Map();
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    createInterface({ input: child.stdout }).on("line", (line) => {
      const msg = JSON.parse(line);
      const waiter = pending.get(msg.id);
      if (waiter) {
        pending.delete(msg.id);
        waiter(msg);
      }
    });

    let nextId = 1;
    const rpc = (method, params) =>
      new Promise((res) => {
        const id = nextId++;
        pending.set(id, res);
        child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
      });

    Promise.resolve()
      .then(() => callback({ rpc, outDir, logPath, getStderr: () => stderr }))
      .then(
        (val) => {
          child.kill("SIGTERM");
          fs.rmSync(tmp, { recursive: true, force: true });
          resolve(val);
        },
        (err) => {
          child.kill("SIGTERM");
          fs.rmSync(tmp, { recursive: true, force: true });
          reject(err);
        },
      );
  });
}

test("stdio MCP server handles initialize, tools/list, six typed operations, errors, and timeouts", async () => {
  await withMcpClient({ DOTRIX_BROWSER_TIMEOUT_MS: "1000" }, async ({ rpc, outDir, logPath, getStderr }) => {
    const init = await rpc("initialize", { protocolVersion: "2025-06-18", capabilities: {} });
    assert.equal(init.result.serverInfo.name, "dotrix-agent-browser");

    const listed = await rpc("tools/list", {});
    assert.deepEqual(
      listed.result.tools.map((t) => t.name),
      BROWSER_TOOLS.map((t) => t.name),
    );

    const opened = await rpc("tools/call", { name: "browser_open", arguments: { url: "http://127.0.0.1:3000/home" } });
    assert.ok(!opened.result.isError);
    assert.match(opened.result.content[0].text, /ran:open http:\/\/127\.0\.0\.1:3000\/home/);

    const snap = await rpc("tools/call", { name: "browser_snapshot", arguments: {} });
    assert.match(snap.result.content[0].text, /ran:snapshot -i/);

    const clicked = await rpc("tools/call", { name: "browser_click", arguments: { ref: "@e3" } });
    assert.match(clicked.result.content[0].text, /ran:click @e3/);

    const filled = await rpc("tools/call", { name: "browser_fill", arguments: { ref: "@e4", text: "ada" } });
    assert.match(filled.result.content[0].text, /ran:fill @e4 ada/);

    const shot = await rpc("tools/call", { name: "browser_screenshot", arguments: { filename: "proof.png" } });
    assert.ok(!shot.result.isError);
    assert.equal(fs.readFileSync(path.join(outDir, "proof.png"), "utf8"), "png-bytes");

    const closed = await rpc("tools/call", { name: "browser_close", arguments: {} });
    assert.match(closed.result.content[0].text, /ran:close/);

    // Blocked metadata URL is refused without invoking agent-browser.
    const blocked = await rpc("tools/call", { name: "browser_open", arguments: { url: "http://169.254.169.254/latest" } });
    assert.equal(blocked.result.isError, true);

    // Non-zero CLI crash returns isError cleanly.
    const crashed = await rpc("tools/call", { name: "browser_open", arguments: { url: "http://127.0.0.1:9999/crash" } });
    assert.equal(crashed.result.isError, true);
    assert.match(crashed.result.content[0].text, /browser process crashed/);

    // Hanging CLI triggers timeout error.
    const timedOut = await rpc("tools/call", { name: "browser_open", arguments: { url: "http://127.0.0.1:9999/hang" } });
    assert.equal(timedOut.result.isError, true);
    assert.match(timedOut.result.content[0].text, /timed out/);

    const recorded = fs
      .readFileSync(logPath, "utf8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    assert.equal(
      recorded.some((args) => args[0] === "open" && String(args[1]).includes("169.254")),
      false,
    );
    assert.match(getStderr(), /browser\.navigation\.completed/);
    assert.match(getStderr(), /browser\.screenshot\.created/);
  });
});
