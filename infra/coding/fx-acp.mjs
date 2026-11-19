// Kai on fx (DOTRIX_CODING_FX): drives `fx acp` (the Agent Client Protocol over stdio) for one coding turn
// in the sandbox, and prints what happens as JSON lines for modules/coding/tools.py (`Fx`):
//
//   {"type":"started","model":…,"resumed":bool,"profileDigest":…}   the session is ready, with its profile's digest
//   {"type":"text","text":…}                          a message of the agent's, whole
//   {"type":"tool","id":…,"name":…,"title":…,"input":{…}}   a tool call starts
//   {"type":"tool_result","id":…,"status":"completed"|"failed","output":…}
//   {"type":"done","stopReason":…,"usage":{…},"final":…}    the turn ended
//   {"type":"warning","message":…}                    something the turn goes on without (the browser didn't start)
//   {"type":"error","message":…}                      it couldn't run (shown to people: never names fx)
//
//   node fx-acp.mjs --base-url URL --key-env NAME --model MODEL [--session ID [--resume]] [--mcp-config JSON]
//                   [--profile BASE64 [--profile-digest SHA256]]  < brief
//
// --profile is Kai's contract from Dotrix (base64 UTF-8 text): a new session gets it as its system profile
// (ACP's systemPrompt) and fx saves it with the session, so a resumed one keeps the profile it started with.
// Its SHA-256 is saved beside fx's session id and reported in `started`; --profile-digest is that digest as
// Dotrix recorded it, and a resumed session whose saved profile differs never runs a turn.
//
// --mcp-config gives fx MCP servers for the turn, in Claude Code's format ({"mcpServers": {name: {command, args}}}):
// the platform passes the browser (playwright-mcp) this way, as it does for Claude Code. They go to fx with each
// session it starts, resumes or loads (ACP's mcpServers), so a resumed conversation has them too.
//
// fx's settings are ours, written each turn: one OpenAI-compatible provider (the person's own, its key
// read from NAME, which the sandbox holds), no auto-upgrade. The session runs in fx's `full-access` mode:
// the sandbox, not fx, is the boundary, and nobody is there to answer a permission prompt. fx's own
// session id is kept under ~/.fx/dotrix so the next turn (with --resume) continues the same conversation;
// the platform saves ~/.fx between turns. SIGINT cancels the turn, which still ends with "done".
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { accessSync, constants, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import http from "node:http";
import https from "node:https";
import { homedir } from "node:os";
import { delimiter, isAbsolute, join } from "node:path";
import { createInterface } from "node:readline";
import tls from "node:tls";

import { answers, notStarted } from "./mcp-check.mjs";

const args = process.argv.slice(2);
const arg = (name) => {
  const at = args.indexOf(name);
  return at >= 0 ? args[at + 1] : undefined;
};
const baseUrl = arg("--base-url");
const keyEnv = arg("--key-env");
const model = arg("--model");
const dotrixSession = arg("--session");
const resume = args.includes("--resume");
const mcpConfig = arg("--mcp-config");
const profile = arg("--profile") ? Buffer.from(arg("--profile"), "base64").toString("utf8") : null;
const pinnedDigest = arg("--profile-digest") ?? null;
const workerArg = arg("--workers") ? JSON.parse(Buffer.from(arg("--workers"), "base64").toString("utf8")) : null;
const fxBin = process.env.DOTRIX_FX_BIN || "fx";

const emit = (event) => process.stdout.write(`${JSON.stringify(event)}\n`);
const fail = (message) => {
  emit({ type: "error", message: String(message).slice(0, 2000) });
  process.exit(1);
};

if (!baseUrl || !keyEnv || !model) fail("The coding engine wasn't set up for this turn (base URL, key or model missing)");
if (dotrixSession && !/^[A-Za-z0-9_-]{1,64}$/.test(dotrixSession)) fail("The coding engine wasn't set up for this turn (invalid session)");

/** A command as fx needs it (0.0.16 takes only an absolute path to an executable): found on PATH like a shell would. */
function executable(command) {
  const runs = (path) => {
    try {
      accessSync(path, constants.X_OK);
      return statSync(path).isFile();
    } catch {
      return false;
    }
  };
  if (isAbsolute(command)) return runs(command) ? command : null;
  if (command.includes("/")) return null;
  for (const dir of (process.env.PATH || "").split(delimiter)) if (dir && isAbsolute(dir) && runs(join(dir, command))) return join(dir, command);
  return null;
}

/** ACP's stdio MCP servers from Claude Code's format; anything malformed fails the turn rather than going unsaid. */
function mcpServersFrom(raw) {
  if (!raw) return [];
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    fail("The coding engine wasn't set up for this turn (invalid MCP servers)");
  }
  const servers = parsed?.mcpServers;
  if (!servers || typeof servers !== "object" || Array.isArray(servers)) fail("The coding engine wasn't set up for this turn (invalid MCP servers)");
  return Object.entries(servers).map(([name, server]) => {
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(name) || typeof server?.command !== "string" || !server.command)
      fail("The coding engine wasn't set up for this turn (invalid MCP server)");
    const command = executable(server.command);
    if (!command) fail(`The coding engine's ${name === "browser" ? "browser" : `${name} tool`} isn't installed in this sandbox`);
    const serverArgs = Array.isArray(server.args) ? server.args.map(String) : [];
    const env = Object.entries(server.env && typeof server.env === "object" ? server.env : {}).map(([key, value]) => ({ name: key, value: String(value) }));
    return { name, command, args: serverArgs, env };
  });
}
// Only the servers that start go to fx; one that doesn't is said, and the turn goes on without it.
const mcpServers = [];
for (const server of mcpServersFrom(mcpConfig)) {
  if (await answers(server)) mcpServers.push(server);
  else emit({ type: "warning", message: notStarted(server.name) });
}

const brief = readFileSync(0, "utf8");
if (!brief.trim()) fail("The coding engine got an empty brief");

// fx (0.0.16) makes its model requests directly and ignores HTTPS_PROXY, but in the Docker sandbox the egress proxy
// is the only way out. So when a proxy is set, fx talks plain HTTP to a forwarder on 127.0.0.1 (fx allows http on
// localhost), which sends each request on to the provider over HTTPS, tunnelled through that proxy. It forwards to
// the configured provider only, so the egress proxy's allowlist stays the boundary. With no proxy, fx goes direct.
const egress = process.env.HTTPS_PROXY || process.env.https_proxy;
let egressRefused = false; // the egress proxy refused the provider: the turn's "refused" is the sandbox's, not the model's

async function forwarder(target, proxy) {
  const upstream = new URL(target);
  const via = new URL(proxy);
  if (upstream.protocol !== "https:") throw new Error("The provider must be HTTPS behind a proxy");
  const agent = new https.Agent({ keepAlive: true });
  agent.createConnection = (options, done) => {
    const connect = http.request({ host: via.hostname, port: via.port || 80, method: "CONNECT", path: `${upstream.hostname}:${upstream.port || 443}` });
    connect.once("connect", (res, socket) => {
      if (res.statusCode !== 200) egressRefused = true;
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
    // A refusal is final (403: fx doesn't retry it); anything else may pass (502: fx retries).
    out.on("error", (error) => {
      if (!res.headersSent) res.writeHead(error.refused ? 403 : 502, { "content-type": "text/plain" });
      res.end(error.refused ? "The sandbox doesn't allow this provider" : "The provider couldn't be reached through the egress proxy");
    });
    req.pipe(out);
  });
  // fx 0.0.17 pins its connection when saving a session. A random port makes
  // every resumed turn look like a different provider. Each sandbox has its own
  // network namespace, so reserve one fixed local relay port and fail on collision.
  await new Promise((resolve, reject) => {
    server.once("error", () => reject(new Error("The model relay port is unavailable; start a fresh coding session")));
    server.listen(31821, "127.0.0.1", resolve);
  });
  server.unref();
  // The provider's path (e.g. /v1) stays; only the origin becomes the forwarder's.
  return `http://127.0.0.1:${server.address().port}${upstream.pathname.replace(/\/$/, "")}`;
}
const providerUrl = egress ? await forwarder(baseUrl, egress) : baseUrl;

// fx's settings: the one provider this turn may use (configured_provider.zig's shape).
const fxHome = join(homedir(), ".fx");
const ours = join(fxHome, "dotrix");
mkdirSync(ours, { recursive: true, mode: 0o700 });
writeFileSync(
  join(fxHome, "settings.json"),
  JSON.stringify({
    provider: "dotrix",
    // The repository is data, never configuration: none of its .fx.json, .fx/agents, skills,
    // .mcp.json or AGENTS.md reaches Kai (fx's project_config; FX_PROJECT_CONFIG below too).
    project_config: false,
    // Kai's workers (subagents) working at once in one turn, the same bound as Dotrix's own parallel builds.
    max_subagents: 2,
    auto_upgrade: false,
    cache_warming: false,
    session_titles: false,
    sound: false,
    providers: {
      dotrix: {
        protocol: "openai-chat-completions",
        base_url: providerUrl,
        auth: { type: "bearer", env: keyEnv },
        model_metadata: { [model]: { supports_tool_use: true } },
      },
    },
    models: { dotrix: model },
  }),
  { mode: 0o600 },
);
const sessionFile = dotrixSession ? join(ours, `${dotrixSession}.json`) : null;
const saved = () => {
  if (!sessionFile) return {};
  try {
    return JSON.parse(readFileSync(sessionFile, "utf8"));
  } catch {
    return {};
  }
};
const savedSession = () => {
  if (!sessionFile) return null;
  try {
    return JSON.parse(readFileSync(sessionFile, "utf8")).fxSession ?? null;
  } catch {
    return null;
  }
};

// Kai's workers (fx agent profiles under ~/.fx/agents): a new session's from --workers, a resumed one's as saved
// with it, so it keeps the workers it started with. The profile digest covers the contract and the workers.
const kept = saved();
const continuing = Boolean(resume && kept.fxSession);
const workerProfiles = continuing ? (kept.workers ?? null) : workerArg;
const digestOf = (text, set) =>
  text && text.trim()
    ? createHash("sha256")
        .update(set ? JSON.stringify({ profile: text, workers: set }) : text, "utf8")
        .digest("hex")
    : null;
if (continuing) {
  // Dotrix's record of the session's profile, and the saved state itself, must agree.
  const recomputed = "profile" in kept ? digestOf(kept.profile, kept.workers ?? null) : (kept.profileDigest ?? null);
  if ((pinnedDigest && kept.profileDigest !== pinnedDigest) || recomputed !== (kept.profileDigest ?? null)) {
    fail("This coding session's saved state doesn't match the profile it was started with; start a new session");
  }
}
const agentsDir = join(fxHome, "agents");
rmSync(agentsDir, { recursive: true, force: true });
for (const worker of workerProfiles ?? []) {
  const name = String(worker?.name ?? "");
  if (!/^[a-z0-9_-]{1,64}$/.test(name) || name === "main" || name === "agent" || !Array.isArray(worker.tools)) {
    fail("Kai's workers couldn't be set up");
  }
  const dir = join(agentsDir, name);
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  const settings = { description: String(worker.description), tools: worker.tools.map(String) };
  if (Array.isArray(worker.mcp_servers)) settings.mcp_servers = worker.mcp_servers.map(String);
  writeFileSync(join(dir, "profile.json"), JSON.stringify(settings), { mode: 0o600 });
  writeFileSync(join(dir, "prompt.md"), `${String(worker.prompt ?? "")}\n`, { mode: 0o600 });
}

const fxEnv = { ...process.env, FX_AUTO_UPGRADE: "0", FX_PROJECT_CONFIG: "0", FX_SOUND: "0", FX_DISABLE_KEYCHAIN: "1", FX_NO_OPEN_BROWSER: "1", NO_COLOR: "1" };
// Upstream fx 0.0.17 reports the same version as the Kai runtime's fx but has no project_config, so it would
// take the repository's configuration: run only an fx that knows the setting and has it off.
const setting = spawnSync(fxBin, ["config", "get", "project_config"], { env: fxEnv, encoding: "utf8", timeout: 15_000 });
if (setting.error) fail(`The coding engine didn't start (${setting.error.code ?? "error"})`);
if (setting.status !== 0 || setting.stdout.trim() !== "false") fail("The coding engine isn't the version Kai was checked with");

// The model is the provider's default in the settings above, not `--model` (that names an AI Gateway model).
const fx = spawn(fxBin, ["acp"], { stdio: ["pipe", "pipe", "inherit"], env: fxEnv });
// The code only: the OS's message names the binary.
fx.on("error", (error) => fail(`The coding engine didn't start (${error.code ?? "error"})`));

// JSON-RPC 2.0 over fx's stdio: our requests, its notifications, and the few requests it makes of us.
let nextId = 1;
const pending = new Map();
const call = (method, params) =>
  new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject, method });
    fx.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
  });
const notify = (method, params) => fx.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`);
const reply = (id, result, error) => fx.stdin.write(`${JSON.stringify(error ? { jsonrpc: "2.0", id, error } : { jsonrpc: "2.0", id, result })}\n`);

// What the agent says arrives in chunks: kept whole, and said when a tool call or the turn's end closes it.
let replaying = false; // session/load replays the conversation so far: not this turn's
let message = "";
let messageId = null;
let lastMessage = "";
const tools = new Map(); // toolCallId → whether its start was said
const flush = () => {
  if (message.trim()) {
    emit({ type: "text", text: message });
    lastMessage = message;
  }
  message = "";
};
const contentText = (content) =>
  (Array.isArray(content) ? content : []).map((item) => (item?.type === "content" && item.content?.type === "text" ? item.content.text : "")).join("");

function onUpdate(update) {
  if (replaying || !update) return;
  const recovery = update._meta?.fx?.modelResponseRecovery;
  if (recovery && ["need_user", "failed"].includes(recovery.state) && !cancelled) {
    providerFailed = true;
    emit({ type: "error", message: "The model request needs attention; check your provider connection and try again" });
    cancel();
  }
  switch (update.sessionUpdate) {
    case "agent_message_chunk": {
      if (update.messageId && update.messageId !== messageId) flush();
      messageId = update.messageId ?? messageId;
      if (update.content?.type === "text") message += update.content.text ?? "";
      break;
    }
    case "tool_call":
    case "tool_call_update": {
      const id = update.toolCallId;
      if (!id) break;
      if (!tools.get(id) && (update.sessionUpdate === "tool_call" || update.name || update.rawInput)) {
        flush();
        tools.set(id, true);
        if (update.name === "subagent") subagentCalls.set(id, update.rawInput?.request?.agent ?? update.rawInput?.agent ?? null);
        emit({ type: "tool", id, name: update.name ?? null, title: update.title ?? null, kind: update.kind ?? null, input: update.rawInput ?? {} });
      }
      if (update.status === "completed" || update.status === "failed") {
        emit({ type: "tool_result", id, status: update.status, output: contentText(update.content).slice(-64_000) });
      }
      break;
    }
    default:
      break; // plans, usage of the context, titles, commands: not what the session shows
  }
}

// Kai's own workers (fx's subagents) run in child sessions, whose tool calls ACP doesn't stream. fx's hook
// events do (libfx/hook, asked for on each session below), so their commands and edits show in the session
// too, named for the worker. The main session's tools come as session/update, so its hooks are skipped.
const hooks = { fx: { hooks: { captureContent: true } } };
const subagentCalls = new Map(); // the main session's subagent call id → the worker it names
const workers = new Map(); // child session id → worker name
const parseJson = (text) => {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
};
function onHook(hook) {
  if (replaying || !hook || typeof hook !== "object") return;
  const data = hook.data ?? {};
  if (hook.type === "delegation" && data.phase === "dispatched" && data.childSessionId) {
    workers.set(data.childSessionId, subagentCalls.get(data.callId) ?? workers.get(hook.sessionId) ?? null);
    return;
  }
  if (!hook.sessionId || hook.sessionId === hook.rootSessionId) return;
  if (hook.type !== "tool.start" && hook.type !== "tool.end") return;
  const callId = data.call?.callId;
  if (!callId) return;
  const id = `${hook.sessionId}:${callId}`;
  if (hook.type === "tool.start") {
    flush();
    const args = parseJson(data.call.argumentsJson ?? "");
    emit({
      type: "tool",
      id,
      name: data.call.name ?? null,
      title: null,
      kind: null,
      input: args && typeof args === "object" ? args : {},
      agent: workers.get(hook.sessionId) ?? "a worker",
    });
    return;
  }
  // A command's result is JSON with what it printed; anything else is its text.
  const result = parseJson(data.output ?? "");
  const output =
    typeof result?.output_delta === "string" ? result.output_delta : typeof result?.output === "string" ? result.output : String(data.output ?? "");
  const failed = data.status !== "success" || (typeof result?.exit_code === "number" && result.exit_code !== 0);
  emit({ type: "tool_result", id, status: failed ? "failed" : "completed", output: output.slice(-64_000) });
}

createInterface({ input: fx.stdout, crlfDelay: Infinity }).on("line", (line) => {
  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    return;
  }
  if (msg.id !== undefined && (msg.result !== undefined || msg.error !== undefined) && pending.has(msg.id)) {
    const { resolve, reject, method } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(Object.assign(new Error(`${method}: ${msg.error.message ?? "failed"}`), { code: msg.error.code }));
    else resolve(msg.result);
    return;
  }
  if (msg.method === "session/update") return onUpdate(msg.params?.update);
  if (msg.method === "libfx/hook") return onHook(msg.params);
  if (msg.method === "session/request_permission" && msg.id !== undefined) {
    // full-access shouldn't ask; if it does, the sandbox is the boundary: allow this once.
    const options = msg.params?.options ?? [];
    const allow = options.find((o) => o.kind === "allow_once") ?? options.find((o) => String(o.kind).startsWith("allow"));
    return reply(msg.id, allow ? { outcome: { outcome: "selected", optionId: allow.optionId } } : { outcome: { outcome: "cancelled" } });
  }
  if (msg.id !== undefined && msg.method) reply(msg.id, null, { code: -32601, message: "Not supported by this client" });
});

let exited = false;
fx.on("exit", (code, signal) => {
  exited = true;
  for (const { reject } of pending.values()) reject(new Error(`The coding engine stopped (${signal ?? code})`));
  pending.clear();
});

let sessionId = null;
let cancelled = false;
let providerFailed = false;
const cancel = () => {
  if (cancelled) return;
  cancelled = true;
  if (sessionId && !exited) notify("session/cancel", { sessionId });
  setTimeout(() => fx.kill("SIGTERM"), 4_000).unref(); // the runner's grace is 5 s
};
process.on("SIGINT", cancel);
process.on("SIGTERM", cancel);

async function open() {
  const cwd = process.cwd();
  const previous = resume ? savedSession() : null;
  if (previous) {
    // The session keeps the profile it was started with (fx restores it), checked above against Dotrix's record.
    replaying = true;
    try {
      try {
        await call("session/resume", { sessionId: previous, cwd, mcpServers, _meta: hooks });
      } catch (error) {
        if (error.code !== -32601) throw error;
        await call("session/load", { sessionId: previous, cwd, mcpServers, _meta: hooks });
      }
      return { id: previous, resumed: true, profileDigest: kept.profileDigest ?? null };
    } catch (error) {
      // Saved state this engine can't read (written by a version that can't be read back, or damaged): the
      // turn starts a new conversation, with this turn's profile, and says so (`fresh` in `started`).
      if (typeof error?.code !== "number") throw error; // the engine itself failed, not the saved state
    } finally {
      replaying = false;
    }
  }
  const systemPrompt = profile && profile.trim() ? [{ type: "text", text: profile }] : undefined;
  const created = await call("session/new", { cwd, mcpServers, ...(systemPrompt ? { systemPrompt } : {}), _meta: hooks });
  if (!created?.sessionId) throw new Error("session/new returned no session");
  const profileDigest = systemPrompt ? digestOf(profile, workerProfiles) : null;
  const record = { fxSession: created.sessionId, profileDigest, ...(systemPrompt ? { profile, workers: workerProfiles } : {}) };
  if (sessionFile) writeFileSync(sessionFile, JSON.stringify(record), { mode: 0o600 });
  return { id: created.sessionId, resumed: false, profileDigest };
}

try {
  await call("initialize", {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false },
    clientInfo: { name: "dotrix", version: "1" },
  });
  const session = await open();
  sessionId = session.id;
  await call("session/set_mode", { sessionId, modeId: "full-access" });
  emit({
    type: "started",
    model,
    resumed: session.resumed,
    ...(session.profileDigest ? { profileDigest: session.profileDigest } : {}),
    ...(resume && !session.resumed ? { fresh: true } : {}),
  });
  if (cancelled) notify("session/cancel", { sessionId });
  const result = await call("session/prompt", { sessionId, prompt: [{ type: "text", text: brief }] });
  flush();
  if (egressRefused) {
    emit({ type: "error", message: "The sandbox doesn't allow this model provider (its egress proxy refused it)" });
    process.exitCode = 1;
  } else {
    emit({
      type: "done",
      stopReason: providerFailed ? "refused" : cancelled ? "cancelled" : (result?.stopReason ?? "end_turn"),
      usage: result?.usage ?? null,
      final: lastMessage,
    });
    if (providerFailed) process.exitCode = 1;
  }
} catch (error) {
  flush();
  if (cancelled) emit({ type: "done", stopReason: providerFailed ? "refused" : "cancelled", usage: null, final: lastMessage });
  else emit({ type: "error", message: String(error?.message ?? error).slice(0, 2000) });
  process.exitCode = cancelled && !providerFailed ? 0 : 1;
} finally {
  // fx ends when its input closes; wait for it, so no fx outlives the turn, and stop it if it doesn't.
  if (!exited) {
    fx.stdin.end();
    await new Promise((resolve) => {
      const stop = setTimeout(() => {
        fx.kill("SIGTERM");
        resolve();
      }, 3_000);
      fx.once("exit", () => {
        clearTimeout(stop);
        resolve();
      });
    });
  }
}
