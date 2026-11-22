// Sandboxed stdio MCP server wrapping the `agent-browser` CLI behind six typed operations.
// Zero third-party dependencies: runs inside the coding image under `/opt/dotrix/agent-browser-mcp.mjs`.
import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

const DEFAULT_OUTPUT_DIR = "/tmp/playwright";
const DEFAULT_TIMEOUT_MS = 30_000;
const MAX_TIMEOUT_MS = 60_000;
const MAX_OUTPUT_BYTES = 65_536;
const MAX_REF_LENGTH = 256;
const MAX_FILL_LENGTH = 32_768;

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);
const METADATA_HOSTS = new Set(["169.254.169.254", "metadata.google.internal", "metadata.goog", "100.100.100.200", "fd00:ec2::254"]);

export const BROWSER_TOOLS = [
  {
    name: "browser_open",
    description: "Open a URL in the sandboxed headless browser.",
    inputSchema: {
      type: "object",
      properties: { url: { type: "string", description: "Target HTTP or HTTPS URL (loopback by default)." } },
      required: ["url"],
      additionalProperties: false,
    },
  },
  {
    name: "browser_snapshot",
    description: "Inspect interactive elements and refs on the active page.",
    inputSchema: {
      type: "object",
      properties: {
        interactive: { type: "boolean", description: "Return interactive refs (-i). Defaults to true." },
      },
      additionalProperties: false,
    },
  },
  {
    name: "browser_click",
    description: "Click an element referenced by an ID or selector from browser_snapshot.",
    inputSchema: {
      type: "object",
      properties: { ref: { type: "string", description: "Element reference or selector." } },
      required: ["ref"],
      additionalProperties: false,
    },
  },
  {
    name: "browser_fill",
    description: "Fill text into an input referenced by an ID or selector from browser_snapshot.",
    inputSchema: {
      type: "object",
      properties: {
        ref: { type: "string", description: "Input element reference or selector." },
        text: { type: "string", description: "Text value to type." },
      },
      required: ["ref", "text"],
      additionalProperties: false,
    },
  },
  {
    name: "browser_screenshot",
    description: "Capture a PNG screenshot into the sandbox browser output directory.",
    inputSchema: {
      type: "object",
      properties: {
        filename: { type: "string", description: "Single-segment PNG filename (for example proof.png)." },
      },
      required: ["filename"],
      additionalProperties: false,
    },
  },
  {
    name: "browser_close",
    description: "Close the active browser session and clean up processes.",
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
  },
];

function hasControlChars(text) {
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    if (code < 32 || code === 127) return true;
  }
  return false;
}

function normalizeHost(hostname) {
  const clean = hostname
    .trim()
    .toLowerCase()
    .replace(/^\[|\]$/g, "");
  return clean.startsWith("::ffff:") ? clean.slice(7) : clean;
}

function isBlockedPrivateOrLinkLocalIp(host) {
  const ipv4 = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (ipv4) {
    const octets = ipv4.slice(1).map((part) => Number(part));
    if (octets.some((n) => n < 0 || n > 255)) return true;
    const [a, b] = octets;
    if (a === 127) return false; // loopback handled separately
    if (a === 0 || a === 10) return true;
    if (a === 169 && b === 254) return true;
    if (a === 172 && b >= 16 && b <= 31) return true;
    if (a === 192 && b === 168) return true;
    if (a === 100 && b >= 64 && b <= 127) return true;
    if (a >= 224) return true;
    return false;
  }
  if (host.includes(":")) {
    if (host === "::1") return false;
    if (host === "::" || host.startsWith("fe80:") || host.startsWith("fc") || host.startsWith("fd") || host.startsWith("ff")) {
      return true;
    }
  }
  return false;
}

/** Validate a navigation URL against scheme, credential, metadata, private-network, and host rules. */
export function validateUrl(raw, allowedHosts = []) {
  if (typeof raw !== "string" || !raw.trim() || hasControlChars(raw)) {
    throw new Error("Invalid URL: expected a single-line HTTP or HTTPS URL.");
  }
  let parsed;
  try {
    parsed = new URL(raw.trim());
  } catch {
    throw new Error("Invalid URL format.");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(`Blocked URL scheme ${parsed.protocol}; only http and https are allowed.`);
  }
  if (parsed.username || parsed.password) {
    throw new Error("URLs containing embedded credentials are not allowed.");
  }
  const host = normalizeHost(parsed.hostname);
  if (!host || METADATA_HOSTS.has(host) || isBlockedPrivateOrLinkLocalIp(host)) {
    throw new Error(`Blocked private or metadata destination: ${parsed.hostname}`);
  }
  const allowSet = new Set(allowedHosts.map((h) => normalizeHost(String(h))).filter(Boolean));
  if (!LOOPBACK_HOSTS.has(host) && !allowSet.has(host)) {
    throw new Error(`Blocked destination host "${parsed.hostname}"; only loopback or allowlisted hosts are permitted.`);
  }
  return parsed.toString();
}

/** Validate an element ref or selector before passing it as an argv token to `agent-browser`. */
export function validateRef(ref) {
  if (typeof ref !== "string") {
    throw new Error("Element ref must be a string.");
  }
  const trimmed = ref.trim();
  if (!trimmed || trimmed.length > MAX_REF_LENGTH || hasControlChars(trimmed)) {
    throw new Error(`Invalid element ref (must be 1-${MAX_REF_LENGTH} printable characters).`);
  }
  return trimmed;
}

/** Confine PNG screenshots to single-segment filenames inside `outputDir`. */
export function validateScreenshotPath(filename, outputDir = DEFAULT_OUTPUT_DIR) {
  if (typeof filename !== "string" || !filename.trim()) {
    throw new Error("Screenshot filename is required.");
  }
  const clean = filename.trim();
  if (hasControlChars(clean) || clean.includes("/") || clean.includes("\\") || clean.includes("..")) {
    throw new Error("Screenshot filename must be a single filename inside the browser output directory.");
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*\.png$/i.test(clean)) {
    throw new Error("Screenshot filename must end in .png and use safe filename characters.");
  }
  const root = path.resolve(outputDir);
  const resolved = path.resolve(root, clean);
  if (path.dirname(resolved) !== root) {
    throw new Error("Screenshot path escapes the browser output directory.");
  }
  return resolved;
}

function clipOutput(text) {
  const normalized = String(text ?? "").trim();
  const buf = Buffer.from(normalized, "utf8");
  if (buf.byteLength <= MAX_OUTPUT_BYTES) return normalized;
  return `${buf.subarray(0, MAX_OUTPUT_BYTES).toString("utf8")}\n... (truncated to ${MAX_OUTPUT_BYTES} bytes)`;
}

export function createBrowserAdapter(options = {}) {
  const outputDir = path.resolve(options.outputDir ?? process.env.DOTRIX_BROWSER_OUTPUT ?? DEFAULT_OUTPUT_DIR);
  const bin = options.bin ?? process.env.DOTRIX_AGENT_BROWSER_BIN ?? "agent-browser";
  const allowedHosts =
    options.allowedHosts ??
    (process.env.DOTRIX_BROWSER_ALLOWED_HOSTS ?? "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  const rawTimeout = Number(options.timeoutMs ?? process.env.DOTRIX_BROWSER_TIMEOUT_MS ?? DEFAULT_TIMEOUT_MS);
  const timeoutMs = Number.isFinite(rawTimeout) && rawTimeout >= 1_000 ? Math.min(rawTimeout, MAX_TIMEOUT_MS) : DEFAULT_TIMEOUT_MS;
  const emitEvents = options.emitEvents ?? process.env.DOTRIX_BROWSER_EVENTS === "1";
  const activeChildren = new Set();

  function logEvent(event, detail = {}) {
    if (!emitEvents) return;
    process.stderr.write(`${JSON.stringify({ event, ts: new Date().toISOString(), ...detail })}\n`);
  }

  function runCli(args) {
    return new Promise((resolve, reject) => {
      const child = execFile(
        bin,
        args,
        {
          timeout: timeoutMs,
          maxBuffer: MAX_OUTPUT_BYTES * 4,
          env: { ...process.env, DOTRIX_BROWSER_OUTPUT: outputDir },
        },
        (error, stdout, stderr) => {
          activeChildren.delete(child);
          if (error) {
            const msg = error.killed
              ? `Browser command timed out after ${timeoutMs}ms`
              : clipOutput(stderr || stdout || error.message || "agent-browser failed");
            reject(new Error(msg));
            return;
          }
          resolve(clipOutput(stdout || stderr || "ok"));
        },
      );
      activeChildren.add(child);
    });
  }

  function cleanup() {
    for (const child of activeChildren) {
      child.kill("SIGTERM");
    }
    activeChildren.clear();
  }

  async function callTool(name, args = {}) {
    const safeArgs = args && typeof args === "object" ? args : {};
    try {
      switch (name) {
        case "browser_open": {
          const url = validateUrl(safeArgs.url, allowedHosts);
          logEvent("browser.session.started", { url });
          const out = await runCli(["open", url]);
          logEvent("browser.navigation.completed", { url });
          return { content: [{ type: "text", text: out }] };
        }
        case "browser_snapshot": {
          const cliArgs = safeArgs.interactive === false ? ["snapshot"] : ["snapshot", "-i"];
          const out = await runCli(cliArgs);
          logEvent("browser.snapshot.created");
          return { content: [{ type: "text", text: out }] };
        }
        case "browser_click": {
          const ref = validateRef(safeArgs.ref);
          const out = await runCli(["click", ref]);
          return { content: [{ type: "text", text: out }] };
        }
        case "browser_fill": {
          const ref = validateRef(safeArgs.ref);
          if (typeof safeArgs.text !== "string" || safeArgs.text.includes("\0") || safeArgs.text.length > MAX_FILL_LENGTH) {
            throw new Error(`Invalid text input (string up to ${MAX_FILL_LENGTH} chars, no null bytes).`);
          }
          const out = await runCli(["fill", ref, safeArgs.text]);
          return { content: [{ type: "text", text: out }] };
        }
        case "browser_screenshot": {
          fs.mkdirSync(outputDir, { recursive: true });
          const target = validateScreenshotPath(safeArgs.filename ?? safeArgs.path, outputDir);
          const out = await runCli(["screenshot", target]);
          logEvent("browser.screenshot.created", { path: target });
          return { content: [{ type: "text", text: out ? `${out}\nSaved: ${target}` : `Saved: ${target}` }] };
        }
        case "browser_close": {
          const out = await runCli(["close"]);
          logEvent("browser.session.closed");
          return { content: [{ type: "text", text: out }] };
        }
        default:
          return { isError: true, content: [{ type: "text", text: `Unknown browser tool: ${name}` }] };
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      logEvent("browser.action.failed", { tool: name, error: message });
      return { isError: true, content: [{ type: "text", text: message }] };
    }
  }

  return { callTool, cleanup, outputDir };
}

function parseOutputDirArg(argv) {
  const idx = argv.indexOf("--output-dir");
  if (idx !== -1 && argv[idx + 1]) return argv[idx + 1];
  return undefined;
}

export function startMcpServer(options = {}) {
  const adapter = createBrowserAdapter(options);
  const send = (msg) => process.stdout.write(`${JSON.stringify(msg)}\n`);
  const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });

  rl.on("line", async (line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    let req;
    try {
      req = JSON.parse(trimmed);
    } catch {
      send({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } });
      return;
    }
    const { id, method, params } = req;
    if (method === "notifications/initialized" || id === undefined) return;
    try {
      if (method === "initialize") {
        send({
          jsonrpc: "2.0",
          id,
          result: {
            protocolVersion: params?.protocolVersion ?? "2025-06-18",
            capabilities: { tools: {} },
            serverInfo: { name: "dotrix-agent-browser", version: "1.0.0" },
          },
        });
      } else if (method === "tools/list") {
        send({ jsonrpc: "2.0", id, result: { tools: BROWSER_TOOLS } });
      } else if (method === "tools/call") {
        const result = await adapter.callTool(params?.name, params?.arguments);
        send({ jsonrpc: "2.0", id, result });
      } else {
        send({ jsonrpc: "2.0", id, error: { code: -32601, message: `Method not found: ${method}` } });
      }
    } catch (error) {
      send({ jsonrpc: "2.0", id, error: { code: -32603, message: error instanceof Error ? error.message : String(error) } });
    }
  });

  const shutdown = () => {
    adapter.cleanup();
    rl.close();
  };
  rl.on("close", () => adapter.cleanup());
  process.on("SIGTERM", () => {
    shutdown();
    process.exit(0);
  });
  process.on("SIGINT", () => {
    shutdown();
    process.exit(0);
  });
  return { adapter, shutdown };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  startMcpServer({ outputDir: parseOutputDirArg(process.argv) });
}
