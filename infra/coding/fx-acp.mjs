// Kai on fx (DOTRIX_CODING_FX): drives `fx acp` (the Agent Client Protocol over stdio) for one coding turn
// in the sandbox, and prints what happens as JSON lines for modules/coding/tools.py (`Fx`):
//
//   {"type":"started","model":…,"resumed":bool,"profileDigest":…}   the session is ready, with its profile's digest
//   {"type":"text","text":…}                          a message of the agent's, whole
//   {"type":"tool","id":…,"name":…,"title":…,"input":{…}}   a tool call starts
//   {"type":"tool_result","id":…,"status":"completed"|"failed","output":…}
//   {"type":"done","stopReason":…,"usage":{…},"final":…}    the turn ended
//   {"type":"warning","message":…}                    something the turn goes on without (the browser didn't start)
//   {"type":"background","task":"command"|"worker","id":…,"state":"running"|"done"|"failed"|"stopped"|"ended","label":…}
//                                                     a command Kai left running, or one of its workers, as it goes;
//                                                     "ended": a worker still at work when the turn ended. Commands
//                                                     keep running after the turn (fx runs in fx-host.mjs, which
//                                                     outlives it): a turn starts by listing those kept from earlier
//   {"type":"steering","open":true}                   the turn's inbox (--steer-dir) takes messages from now on
//   {"type":"steer","id":…,"state":"sent"|"accepted"|"delivered"|"cancelled"|"rejected"[,"message":…]}
//                                                     a person's message to the running turn (--steer-dir), as it goes
//   {"type":"error","message":…}                      it couldn't run (shown to people: never names fx)
//
//   node fx-acp.mjs --base-url URL --key-env NAME --model MODEL [--session ID [--resume]] [--mcp-config JSON]
//                   [--profile BASE64 [--profile-digest SHA256]] [--steer-dir NAME]  < brief
//
// --profile is Kai's contract from Dotrix (base64 UTF-8 text): a new session gets it as its system profile
// (ACP's systemPrompt) and fx saves it with the session, so a resumed one keeps the profile it started with.
// Its SHA-256 is saved beside fx's session id and reported in `started`; --profile-digest is that digest as
// Dotrix recorded it, and a resumed session whose saved profile differs never runs a turn.
//
// --steer-dir names this turn's inbox, ~/.fx/dotrix/steer/NAME: while the turn works, the platform drops a
// person's messages there as <id>.txt (written to a dot-file, then renamed), and each goes to fx as a steering
// prompt (`_meta.fx.steer`), which joins the running turn at its next step. Its states are reported as
// `steer` lines: sent; accepted once fx gives it to the model; delivered when the turn that took it ends,
// cancelled when the turn is stopped first, rejected with fx's reason. The inbox closes when the turn's own
// prompt ends, before `done`: anything left in it was never sent, and the platform keeps it for the next turn.
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
//
// fx itself runs in fx-host.mjs, started by the first turn in a sandbox and kept running between turns, so the
// commands Kai leaves running (a long test suite, a local CI run) keep running into the next turn, where the
// session is still open and they're named to Kai. A fresh sandbox (a cold start, a woken one) starts a new host.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { accessSync, constants, mkdirSync, readdirSync, readFileSync, rmSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import net from "node:net";
import { homedir } from "node:os";
import { delimiter, dirname, isAbsolute, join } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

import { HOST_DIR, HOST_REFUSED, HOST_SOCKET, RELAY_PORT } from "./fx-host.mjs";
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
const steerName = arg("--steer-dir");
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

// fx makes its model requests directly and ignores HTTPS_PROXY, but in the Docker sandbox the egress proxy is the
// only way out. So when a proxy is set, fx talks plain HTTP to a relay on 127.0.0.1 (fx allows http on localhost),
// which sends each request on to the provider over HTTPS, tunnelled through that proxy, and to that provider only,
// so the egress proxy's allowlist stays the boundary. The relay runs in the host (fx-host.mjs), beside fx. With no
// proxy, fx goes direct.
const egress = process.env.HTTPS_PROXY || process.env.https_proxy;
let egressRefused = false; // the egress proxy refused the provider: the turn's "refused" is the sandbox's, not the model's
const turnStarted = Date.now();
const refusedSince = () => {
  try {
    return Number(readFileSync(HOST_REFUSED, "utf8")) >= turnStarted;
  } catch {
    return false;
  }
};
if (egress && new URL(baseUrl).protocol !== "https:") fail("The provider must be HTTPS behind a proxy");
// The provider's path (e.g. /v1) stays; only the origin becomes the relay's.
const providerUrl = egress ? `http://127.0.0.1:${RELAY_PORT}${new URL(baseUrl).pathname.replace(/\/$/, "")}` : baseUrl;

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
  // A record from before profiles were saved has neither profile nor workers and keeps its digest as it is; one
  // with workers but no profile can't be checked, so its workers could have been changed: refuse it.
  const legacy = !("profile" in kept) && kept.workers == null;
  const recomputed = legacy ? (kept.profileDigest ?? null) : digestOf(kept.profile, kept.workers ?? null);
  if ((!legacy && !("profile" in kept)) || (pinnedDigest && kept.profileDigest !== pinnedDigest) || recomputed !== (kept.profileDigest ?? null)) {
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
  // The worker's own limits on a turn (the Kai runtime's profile keys): whole numbers, or none.
  for (const key of ["max_steps", "max_tokens"]) {
    if (worker[key] === undefined) continue;
    if (!Number.isSafeInteger(worker[key]) || worker[key] < 1) fail("Kai's workers couldn't be set up");
    settings[key] = worker[key];
  }
  writeFileSync(join(dir, "profile.json"), JSON.stringify(settings), { mode: 0o600 });
  writeFileSync(join(dir, "prompt.md"), `${String(worker.prompt ?? "")}\n`, { mode: 0o600 });
}

const fxEnv = { ...process.env, FX_AUTO_UPGRADE: "0", FX_PROJECT_CONFIG: "0", FX_SOUND: "0", FX_DISABLE_KEYCHAIN: "1", FX_NO_OPEN_BROWSER: "1", NO_COLOR: "1" };
// Upstream fx 0.0.17 reports the same version as the Kai runtime's fx but has no project_config, so it would
// take the repository's configuration: run only an fx that knows the setting and has it off.
const setting = spawnSync(fxBin, ["config", "get", "project_config"], { env: fxEnv, encoding: "utf8", timeout: 15_000 });
if (setting.error) fail(`The coding engine didn't start (${setting.error.code ?? "error"})`);
if (setting.status !== 0 || setting.stdout.trim() !== "false") fail("The coding engine isn't the version Kai was checked with");

// fx runs in the host (fx-host.mjs), which outlives the turn so the commands Kai leaves running keep running into
// the next one; this driver attaches to it. The host is for one configuration (HOST_KEY): another model, provider,
// MCP servers or workers stop it, with what it runs, and a new one starts. The model is the provider's default in the
// settings above, not `--model` (that names an AI Gateway model).
const HOST_KEY = createHash("sha256")
  .update(JSON.stringify({ baseUrl, keyEnv, model, fxBin, mcpServers, workers: workerProfiles ?? null }))
  .digest("hex");
const here = dirname(fileURLToPath(import.meta.url));

function connect() {
  return new Promise((resolve) => {
    const socket = net.createConnection(HOST_SOCKET);
    socket.once("connect", () => resolve(socket));
    socket.once("error", () => resolve(null));
  });
}
/** Attach to the host: its hello and the socket, or null when there's none (or it gave way to this configuration). */
async function attach() {
  const socket = await connect();
  if (!socket) return null;
  const lines = createInterface({ input: socket, crlfDelay: Infinity });
  const hello = await new Promise((resolve) => {
    lines.once("line", (line) => {
      try {
        resolve(JSON.parse(line)?.host?.hello ?? null);
      } catch {
        resolve(null);
      }
    });
    socket.once("close", () => resolve(null));
    socket.write(`${JSON.stringify({ host: { hello: { key: HOST_KEY } } })}\n`);
  });
  if (!hello?.ok) {
    lines.close();
    socket.destroy();
    return hello?.busy ? { busy: true } : null;
  }
  return { socket, lines, hello };
}
async function startHost() {
  rmSync(HOST_SOCKET, { force: true });
  mkdirSync(HOST_DIR, { recursive: true, mode: 0o700 });
  // Detached from the turn at once (its shell exits), so stopping the turn's process tree doesn't stop it.
  const started = spawnSync(
    "sh",
    [
      "-c",
      'log="${DOTRIX_FX_HOST_LOG:-/dev/null}"; if command -v setsid >/dev/null 2>&1; then setsid "$@" </dev/null >>"$log" 2>&1 & else "$@" </dev/null >>"$log" 2>&1 & fi',
      "sh",
      process.execPath,
      join(here, "fx-host.mjs"),
      "--key",
      HOST_KEY,
      ...(egress ? ["--relay-target", baseUrl] : []),
    ],
    { env: fxEnv, stdio: "ignore", timeout: 15_000 },
  );
  if (started.error || started.status !== 0) fail(`The coding engine didn't start (${started.error?.code ?? "error"})`);
  for (let waited = 0; waited < 30_000; waited += 100) {
    const found = await attach();
    if (found && !found.busy) return found;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  fail("The coding engine didn't start (it didn't answer)");
}
let host = await attach();
if (host?.busy) fail("Another turn is still using this coding session's engine");
const kept_host = Boolean(host);
if (!host) {
  // None, or one for another configuration, which is stopping: wait for it to go before starting this one's.
  for (let waited = 0; waited < 5_000 && (await connect().then((s) => (s ? (s.destroy(), true) : false))); waited += 100) {
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  host = await startHost();
}
const fx = host.socket;

// JSON-RPC 2.0 with fx, through the host: our requests, its notifications, and the few requests it makes of us.
let nextId = 1;
const pending = new Map();
const send = (msg) => {
  if (!fx.destroyed) fx.write(`${JSON.stringify(msg)}\n`);
};
const call = (method, params, id = nextId++) =>
  new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject, method });
    send({ jsonrpc: "2.0", id, method, params });
  });
const notify = (method, params) => send({ jsonrpc: "2.0", method, params });
const reply = (id, result, error) => send(error ? { jsonrpc: "2.0", id, error } : { jsonrpc: "2.0", id, result });

// What the agent says arrives in chunks: kept whole, and said when a tool call or the turn's end closes it.
let replaying = false; // session/load replays the conversation so far: not this turn's
let message = "";
let messageId = null;
let lastMessage = "";
const tools = new Map(); // toolCallId → whether its start was said
// Kai's background tasks: commands it left running (fx's `_meta.fx.shell` on a shell call's update, by session id)
// and its workers (subagent messages, by name), each with its label and whether it's still running.
const toolInputs = new Map(); // toolCallId → its name and input, for the label of what a result reports
const background = new Map(); // "command:<id>" | "worker:<name>" → { label, running }
const backgroundState = (task, id, state, label) => {
  const key = `${task}:${id}`;
  const known = background.get(key);
  const shown = label ?? known?.label ?? id;
  if (known && !known.running && state === "running") return; // a finished one isn't started again by a late report
  background.set(key, { label: shown, running: state === "running" });
  emit({ type: "background", task, id, state, label: shown.slice(0, 300) });
};
/** fx/shells' report as the commands Codes lists: running, done (exit 0), failed, or stopped. */
function shellsFrom(shells) {
  return (Array.isArray(shells) ? shells : [])
    .filter((shell) => typeof shell?.sessionId === "string" && typeof shell?.command === "string")
    .map((shell) => {
      const failed = shell.state === "lost" || (shell.state === "completed" && (shell.exitCode ?? (shell.signal ? 1 : 0)) !== 0);
      const state = shell.state === "running" ? "running" : shell.state === "stopped" ? "stopped" : failed ? "failed" : "done";
      const summary = shell.exitCode != null ? `exit ${shell.exitCode}` : shell.signal ? `signal ${shell.signal}` : shell.state;
      return { id: shell.sessionId, command: shell.command, state, summary };
    });
}
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
        toolInputs.set(id, { name: update.name ?? null, input: update.rawInput ?? {} });
        const input = update.rawInput ?? {};
        if (update.name === "subagent" && input.action === "message" && typeof input.agent === "string") {
          backgroundState("worker", input.agent, "running", `${input.agent}: ${String(input.message ?? "").slice(0, 200)}`);
        }
        if (update.name === "subagent") subagentCalls.set(id, update.rawInput?.request?.agent ?? update.rawInput?.agent ?? null);
        emit({ type: "tool", id, name: update.name ?? null, title: update.title ?? null, kind: update.kind ?? null, input: update.rawInput ?? {} });
      }
      const shell = update._meta?.fx?.shell;
      if (shell && typeof shell.sessionId === "string" && (update.status === "completed" || update.status === "failed")) {
        const call = toolInputs.get(id);
        const command = call?.input?.action === "run" && typeof call.input.command === "string" ? call.input.command : null;
        const state =
          shell.state === "running"
            ? "running"
            : shell.state === "stopped"
              ? "stopped"
              : shell.state === "completed" && (shell.exitCode ?? 0) === 0
                ? "done"
                : "failed";
        backgroundState("command", shell.sessionId, state, command);
      }
      const report = update.status === "completed" && toolInputs.get(id)?.name === "subagent" ? contentText(update.content) : "";
      if (report.startsWith("Subagent report")) {
        const found = parseJson(report.slice(report.indexOf("\n") + 1).trim());
        if (found && typeof found.agent === "string") {
          backgroundState("worker", found.agent, found.outcome === "completed" ? "done" : found.outcome === "stopped" ? "stopped" : "failed");
        }
      }
      if (update.status === "completed" || update.status === "failed") {
        emit({ type: "tool_result", id, status: update.status, output: contentText(update.content).slice(-64_000) });
      }
      break;
    }
    case "user_message_chunk": {
      // fx replays a steering prompt as the person's message once it hands it to the model.
      const steerId = steeringIds.get(update._meta?.fx?.steering?.requestId);
      if (steerId && !accepted.has(steerId)) {
        accepted.add(steerId);
        emit({ type: "steer", id: steerId, state: "accepted" });
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

host.lines.on("line", (line) => {
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
fx.on("close", () => {
  exited = true;
  for (const { reject } of pending.values()) reject(new Error("The coding engine stopped"));
  pending.clear();
});

let sessionId = null;
let cancelled = false;
let providerFailed = false;
const cancel = () => {
  if (cancelled) return;
  cancelled = true;
  if (sessionId && !exited) notify("session/cancel", { sessionId });
  // The runner's grace is 5 s: past 4, let go of the engine (the host cancels the prompt of a driver that left).
  setTimeout(() => fx.destroy(), 4_000).unref();
};
process.on("SIGINT", cancel);
process.on("SIGTERM", cancel);

async function open() {
  const cwd = process.cwd();
  const previous = resume ? savedSession() : null;
  if (previous && host.hello.session === previous) {
    // Still open in the host from the last turn, with its commands: the conversation goes on as it is.
    return { id: previous, resumed: true, profileDigest: kept.profileDigest ?? null };
  }
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

// A person's messages to the running turn (--steer-dir), in the order they were written (ids sort by time).
const steerDir = steerName && /^[0-9a-f]{32}$/.test(steerName) ? join(ours, "steer", steerName) : null;
const steeringIds = new Map(); // the steering prompt's JSON-RPC id → the platform's id for the message
const accepted = new Set();
const steers = []; // each sent message's outcome
const extraUsage = []; // a steer fx ran as a turn of its own (it came as the turn closed input): its usage
let steerOpen = false;
let steerTimer = null;
const sendSteers = () => {
  if (!steerOpen || !steerDir || !sessionId || cancelled) return;
  let names = [];
  try {
    names = readdirSync(steerDir)
      .filter((name) => /^[0-9a-f-]{36}\.txt$/.test(name))
      .sort();
  } catch {
    return; // nothing yet
  }
  for (const name of names) {
    const id = name.slice(0, -4);
    let text;
    try {
      text = readFileSync(join(steerDir, name), "utf8");
      unlinkSync(join(steerDir, name));
    } catch {
      continue;
    }
    if (!text.trim()) {
      emit({ type: "steer", id, state: "rejected", message: "The message was empty" });
      continue;
    }
    flush();
    const requestId = nextId++;
    steeringIds.set(requestId, id);
    emit({ type: "steer", id, state: "sent" });
    steers.push(
      call("session/prompt", { sessionId, prompt: [{ type: "text", text }], _meta: { fx: { steer: true } } }, requestId).then(
        (result) => {
          const how = result?._meta?.fx?.steering;
          if (!how && result?.usage) extraUsage.push(result.usage); // ran as its own turn: still this turn's
          emit({ type: "steer", id, state: how === "dropped" || result?.stopReason === "cancelled" ? "cancelled" : "delivered" });
        },
        (error) => emit({ type: "steer", id, state: cancelled ? "cancelled" : "rejected", message: String(error?.message ?? error).slice(0, 200) }),
      ),
    );
  }
};
const closeSteering = async () => {
  if (!steerOpen) return;
  steerOpen = false; // what's left in the inbox was never sent: the platform keeps it for the next turn
  clearInterval(steerTimer);
  // Closed for the platform too: a message it drops from now on is refused, and goes to the next turn.
  rmSync(steerDir, { recursive: true, force: true });
  await Promise.allSettled(steers);
};
const sumUsage = (base) => {
  if (!extraUsage.length) return base;
  const total = { ...(base ?? {}) };
  for (const more of extraUsage) {
    for (const [key, value] of Object.entries(more)) if (typeof value === "number") total[key] = (total[key] ?? 0) + value;
  }
  return total;
};

try {
  // The host initialized fx when it started it.
  const session = await open();
  sessionId = session.id;
  send({ host: { session: sessionId } });
  await call("session/set_mode", { sessionId, modeId: "full-access" });
  emit({
    type: "started",
    model,
    resumed: session.resumed,
    ...(session.profileDigest ? { profileDigest: session.profileDigest } : {}),
    ...(resume && !session.resumed ? { fresh: true } : {}),
  });
  if (cancelled) notify("session/cancel", { sessionId });
  if (steerDir) {
    try {
      // Earlier turns' inboxes are gone with them; this one starts empty.
      rmSync(join(ours, "steer"), { recursive: true, force: true });
      mkdirSync(steerDir, { recursive: true, mode: 0o700 });
      emit({ type: "steering", open: true });
      steerOpen = true;
      steerTimer = setInterval(sendSteers, 250);
    } catch {
      // Without an inbox the turn goes on; messages sent to it are queued for the next turn instead.
    }
  }
  // The commands still kept from earlier turns (or finished since, and not yet read): listed in Codes as this
  // turn's, and named to Kai, who reads one's output with the shell tool's `interact` and its session id.
  const earlier = kept_host && session.resumed ? shellsFrom(host.hello.shells) : [];
  for (const shell of earlier) backgroundState("command", shell.id, shell.state, shell.command);
  const note = earlier.length
    ? `Commands you left running in earlier turns (the shell tool's session ids):\n${earlier
        .map((shell) => `- ${shell.id}: \`${shell.command.slice(0, 200)}\` ${shell.state === "running" ? "is still running" : `finished (${shell.summary})`}`)
        .join("\n")}\nRead one's output with the shell tool's interact action and its session_id.\n\n`
    : "";
  const prompt = call("session/prompt", { sessionId, prompt: [{ type: "text", text: note + brief }] });
  const result = await prompt.finally(closeSteering);
  flush();
  // Commands keep running in the host, into the next turn; a worker still at work when the turn ends ends with it.
  for (const [key, task] of background) {
    if (task.running && key.startsWith("worker:")) backgroundState("worker", key.slice("worker:".length), "ended");
  }
  egressRefused = refusedSince();
  if (egressRefused) {
    emit({ type: "error", message: "The sandbox doesn't allow this model provider (its egress proxy refused it)" });
    process.exitCode = 1;
  } else {
    emit({
      type: "done",
      stopReason: providerFailed ? "refused" : cancelled ? "cancelled" : (result?.stopReason ?? "end_turn"),
      usage: sumUsage(result?.usage ?? null),
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
  // fx stays in the host for the next turn; this turn lets go of it.
  host.lines.close();
  fx.end();
  fx.destroy();
}
