// Kai's fx between turns: one `fx acp` per sandbox, kept running after a turn's driver (fx-acp.mjs) ends, so the
// commands Kai left running (fx keeps them as long as its process lives: a test suite, a local CI run, a dev
// server) keep running into the next turn. fx-acp.mjs starts it once and attaches to it each turn.
//
//   node fx-host.mjs --key DIGEST --relay-target URL      (started by fx-acp.mjs, detached from the turn)
//
// It listens on HOST_SOCKET (~/.dotrix-fx-host/host.sock, outside ~/.fx, which is saved between sandboxes) for one
// driver at a time, newline-delimited JSON:
//
//   driver → {"host":{"hello":{"key":DIGEST}}}
//   host   → {"host":{"hello":{"ok":true,"session":FX_SESSION|null,"shells":[…]}}}  or  {"host":{"hello":{"ok":false}}}
//   driver → {"host":{"session":FX_SESSION}}            the fx session the driver opened
//   then JSON-RPC both ways, relayed to and from fx as it is (the host has already initialized fx).
//
// A different DIGEST (another model, provider, profile, workers or MCP servers) means another fx: the host stops,
// with its commands, and the driver starts a new one. A driver that goes away mid-prompt has its prompt
// cancelled. Every 5 s the host asks fx for its commands (`fx/shells`, the Kai runtime from 0.0.17-kai.3) and
// writes them to HOST_SHELLS (`{"updatedMs":…,"shells":[{sessionId,command,state,exitCode?,signal?,output,startedMs}]}`),
// which the platform reads between turns to say in Codes when one finishes. The host ends when fx does.
//
// The model relay (fx ignores HTTPS_PROXY; see fx-acp.mjs) lives here too, since fx's settings point at it.
import { spawn } from "node:child_process";
import { mkdirSync, renameSync, rmSync, writeFileSync } from "node:fs";
import http from "node:http";
import https from "node:https";
import net from "node:net";
import { homedir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";
import tls from "node:tls";

export const HOST_DIR = join(homedir(), ".dotrix-fx-host");
export const HOST_SOCKET = join(HOST_DIR, "host.sock");
export const HOST_SHELLS = join(HOST_DIR, "shells.json");
export const HOST_PID = join(HOST_DIR, "pid");
export const HOST_REFUSED = join(HOST_DIR, "refused"); // when the egress proxy last refused the provider
export const RELAY_PORT = 31821;
const POLL_MS = Number(process.env.DOTRIX_FX_HOST_POLL_MS) || 5_000;

/** The model relay: plain HTTP on 127.0.0.1 to the provider over HTTPS, tunnelled through the egress proxy. It
 *  forwards to that provider only, so the proxy's allowlist stays the boundary. A refusal is final (403). */
export async function relay(target, proxy, port = RELAY_PORT) {
  const upstream = new URL(target);
  const via = new URL(proxy);
  if (upstream.protocol !== "https:") throw new Error("The provider must be HTTPS behind a proxy");
  const agent = new https.Agent({ keepAlive: true });
  agent.createConnection = (options, done) => {
    const connect = http.request({ host: via.hostname, port: via.port || 80, method: "CONNECT", path: `${upstream.hostname}:${upstream.port || 443}` });
    connect.once("connect", (res, socket) => {
      if (res.statusCode !== 200) return done(Object.assign(new Error(`The egress proxy refused the provider (${res.statusCode})`), { refused: true }));
      done(null, tls.connect({ socket, servername: upstream.hostname }));
    });
    connect.once("error", done);
    connect.end();
  };
  const server = http.createServer((req, res) => {
    const out = https.request(
      { host: upstream.hostname, port: upstream.port || 443, method: req.method, path: req.url, agent, headers: { ...req.headers, host: upstream.host } },
      (answer) => {
        res.writeHead(answer.statusCode ?? 502, answer.headers);
        answer.pipe(res);
      },
    );
    out.on("error", (error) => {
      // The driver tells "the sandbox refused the provider" from the model's own refusal by this file's time.
      if (error.refused) writeFileSync(HOST_REFUSED, String(Date.now()), { mode: 0o600 });
      if (!res.headersSent) res.writeHead(error.refused ? 403 : 502, { "content-type": "text/plain" });
      res.end(error.refused ? "The sandbox doesn't allow this provider" : "The provider couldn't be reached through the egress proxy");
    });
    req.pipe(out);
  });
  // fx pins its connection when saving a session, so the port is fixed: a random one would look like another provider.
  await new Promise((resolve, reject) => {
    server.once("error", () => reject(new Error("The model relay port is unavailable; start a fresh coding session")));
    server.listen(port, "127.0.0.1", resolve);
  });
  return server;
}

async function main() {
  const args = process.argv.slice(2);
  const arg = (name) => {
    const at = args.indexOf(name);
    return at >= 0 ? args[at + 1] : undefined;
  };
  const key = arg("--key");
  const relayTarget = arg("--relay-target");
  const fxBin = process.env.DOTRIX_FX_BIN || "fx";
  mkdirSync(HOST_DIR, { recursive: true, mode: 0o700 });
  writeFileSync(HOST_PID, String(process.pid), { mode: 0o600 });

  const egress = process.env.HTTPS_PROXY || process.env.https_proxy;
  if (egress && relayTarget) await relay(relayTarget, egress);

  const fx = spawn(fxBin, ["acp"], { stdio: ["pipe", "pipe", "inherit"], env: process.env });
  let client = null; // the attached driver's socket
  let fxSession = null;
  let shells = [];
  let nextId = 1;
  const mine = new Map(); // our request ids ("host-N") → resolve
  const prompts = new Set(); // the driver's session/prompt ids still unanswered
  const toFx = (msg) => fx.stdin.write(`${JSON.stringify(msg)}\n`);
  // Our own requests: answered, or given up on after `wait` ms (an fx that never answers one isn't waited for).
  const call = (method, params, wait = 0) =>
    new Promise((resolve) => {
      const id = `host-${nextId++}`;
      const timer = wait ? setTimeout(() => mine.delete(id) && resolve({ error: { code: -32000, message: "no answer" } }), wait) : null;
      mine.set(id, (msg) => {
        if (timer) clearTimeout(timer);
        resolve(msg);
      });
      toFx({ jsonrpc: "2.0", id, method, params });
    });
  const toClient = (line) => {
    if (client && !client.destroyed) client.write(`${line}\n`);
  };
  const end = (code, signal) => {
    process.stderr.write(`fx-host: fx ended (${signal ?? code})\n`);
    rmSync(HOST_SOCKET, { force: true });
    process.exit(0);
  };
  fx.on("exit", end);
  fx.on("error", (error) => end(error.code ?? "error"));

  createInterface({ input: fx.stdout, crlfDelay: Infinity }).on("line", (line) => {
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      return;
    }
    if (typeof msg.id === "string" && mine.has(msg.id) && !msg.method) {
      mine.get(msg.id)(msg);
      mine.delete(msg.id);
      return;
    }
    if (msg.id !== undefined && !msg.method) prompts.delete(msg.id);
    if (client) return toClient(line);
    // Nobody attached: fx asking something is answered as the driver would (full-access shouldn't ask; allow once).
    if (msg.method === "session/request_permission" && msg.id !== undefined) {
      const options = msg.params?.options ?? [];
      const allow = options.find((o) => o.kind === "allow_once") ?? options.find((o) => String(o.kind).startsWith("allow"));
      toFx({
        jsonrpc: "2.0",
        id: msg.id,
        result: allow ? { outcome: { outcome: "selected", optionId: allow.optionId } } : { outcome: { outcome: "cancelled" } },
      });
    } else if (msg.id !== undefined && msg.method) {
      toFx({ jsonrpc: "2.0", id: msg.id, error: { code: -32601, message: "Not supported by this client" } });
    }
  });

  const initialized = await call("initialize", {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false },
    clientInfo: { name: "dotrix", version: "1" },
  });
  if (initialized.error) process.exit(1);

  let reporting = true; // an fx without fx/shells (before kai.3) still keeps its commands; it just can't list them
  const poll = async () => {
    if (!reporting) return;
    const answer = await call("fx/shells", {}, 3_000);
    if (answer.error) {
      if (answer.error.code === -32601 || answer.error.code === -32000) reporting = false;
      return;
    }
    shells = Array.isArray(answer.result?.shells) ? answer.result.shells : [];
    const temp = `${HOST_SHELLS}.tmp`;
    writeFileSync(temp, JSON.stringify({ updatedMs: Date.now(), shells }), { mode: 0o600 });
    renameSync(temp, HOST_SHELLS);
  };
  await poll();
  setInterval(() => poll().catch(() => {}), POLL_MS);

  rmSync(HOST_SOCKET, { force: true });
  const server = net.createServer((socket) => {
    if (client) {
      socket.end(`${JSON.stringify({ host: { hello: { ok: false, busy: true } } })}\n`);
      return;
    }
    let hello = false;
    socket.setEncoding("utf8");
    createInterface({ input: socket, crlfDelay: Infinity }).on("line", (line) => {
      let msg;
      try {
        msg = JSON.parse(line);
      } catch {
        return;
      }
      if (msg.host) {
        if (msg.host.hello && !hello) {
          if (msg.host.hello.key !== key) {
            // Another configuration: this fx (and what it runs) gives way to a new one.
            socket.end(`${JSON.stringify({ host: { hello: { ok: false } } })}\n`, () => fx.kill("SIGTERM"));
            return;
          }
          hello = true;
          client = socket;
          poll()
            .catch(() => {})
            .finally(() => socket.write(`${JSON.stringify({ host: { hello: { ok: true, session: fxSession, shells } } })}\n`));
        } else if (typeof msg.host.session === "string") {
          fxSession = msg.host.session;
        }
        return;
      }
      if (!hello) return;
      if (msg.method === "session/prompt" && msg.id !== undefined && !msg.params?._meta?.fx?.steer) prompts.add(msg.id);
      toFx(msg);
    });
    const detach = () => {
      if (client !== socket) return;
      client = null;
      // A driver gone mid-prompt (stopped, killed): its turn is cancelled, not left working unseen.
      if (prompts.size && fxSession) toFx({ jsonrpc: "2.0", method: "session/cancel", params: { sessionId: fxSession } });
      prompts.clear();
    };
    socket.on("close", detach);
    socket.on("error", detach);
  });
  server.listen(HOST_SOCKET);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    process.stderr.write(`fx-host: ${error?.stack ?? error}\n`);
    process.exit(1);
  });
}
