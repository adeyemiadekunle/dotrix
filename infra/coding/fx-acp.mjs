// Kai on fx (DOTRIX_CODING_FX): drives `fx acp` (the Agent Client Protocol over stdio) for one coding turn
// in the sandbox, and prints what happens as JSON lines for modules/coding/tools.py (`Fx`):
//
//   {"type":"started","model":…,"resumed":bool}      the session is ready
//   {"type":"text","text":…}                          a message of the agent's, whole
//   {"type":"tool","id":…,"name":…,"title":…,"input":{…}}   a tool call starts
//   {"type":"tool_result","id":…,"status":"completed"|"failed","output":…}
//   {"type":"done","stopReason":…,"usage":{…},"final":…}    the turn ended
//   {"type":"error","message":…}                      it couldn't run (shown to people: never names fx)
//
//   node fx-acp.mjs --base-url URL --key-env NAME --model MODEL [--session ID [--resume]]  < brief
//
// fx's settings are ours, written each turn: one OpenAI-compatible provider (the person's own, its key
// read from NAME, which the sandbox holds), no auto-upgrade. The session runs in fx's `full-access` mode:
// the sandbox, not fx, is the boundary, and nobody is there to answer a permission prompt. fx's own
// session id is kept under ~/.fx/dotrix so the next turn (with --resume) continues the same conversation;
// the platform saves ~/.fx between turns. SIGINT cancels the turn, which still ends with "done".
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline";

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
const fxBin = process.env.DOTRIX_FX_BIN || "fx";

const emit = (event) => process.stdout.write(`${JSON.stringify(event)}\n`);
const fail = (message) => {
  emit({ type: "error", message: String(message).slice(0, 2000) });
  process.exit(1);
};

if (!baseUrl || !keyEnv || !model) fail("The coding engine wasn't set up for this turn (base URL, key or model missing)");
if (dotrixSession && !/^[A-Za-z0-9_-]{1,64}$/.test(dotrixSession)) fail("The coding engine wasn't set up for this turn (invalid session)");

const brief = readFileSync(0, "utf8");
if (!brief.trim()) fail("The coding engine got an empty brief");

// fx's settings: the one provider this turn may use (configured_provider.zig's shape).
const fxHome = join(homedir(), ".fx");
const ours = join(fxHome, "dotrix");
mkdirSync(ours, { recursive: true, mode: 0o700 });
writeFileSync(
  join(fxHome, "settings.json"),
  JSON.stringify({
    provider: "dotrix",
    auto_upgrade: false,
    providers: {
      dotrix: {
        protocol: "openai-chat-completions",
        base_url: baseUrl,
        auth: { type: "bearer", env: keyEnv },
        model_metadata: { [model]: { supports_tool_use: true } },
      },
    },
    models: { dotrix: model },
  }),
  { mode: 0o600 },
);
const sessionFile = dotrixSession ? join(ours, `${dotrixSession}.json`) : null;
const savedSession = () => {
  if (!sessionFile) return null;
  try {
    return JSON.parse(readFileSync(sessionFile, "utf8")).fxSession ?? null;
  } catch {
    return null;
  }
};

// The model is the provider's default in the settings above, not `--model` (that names an AI Gateway model).
const fx = spawn(fxBin, ["acp"], {
  stdio: ["pipe", "pipe", "inherit"],
  env: { ...process.env, FX_AUTO_UPGRADE: "0", FX_SOUND: "0", FX_DISABLE_KEYCHAIN: "1", FX_NO_OPEN_BROWSER: "1", NO_COLOR: "1" },
});
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
    replaying = true;
    try {
      try {
        await call("session/resume", { sessionId: previous, cwd, mcpServers: [] });
      } catch (error) {
        if (error.code !== -32601) throw error;
        await call("session/load", { sessionId: previous, cwd, mcpServers: [] });
      }
      return { id: previous, resumed: true };
    } finally {
      replaying = false;
    }
  }
  const created = await call("session/new", { cwd, mcpServers: [] });
  if (!created?.sessionId) throw new Error("session/new returned no session");
  if (sessionFile) writeFileSync(sessionFile, JSON.stringify({ fxSession: created.sessionId }), { mode: 0o600 });
  return { id: created.sessionId, resumed: false };
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
  emit({ type: "started", model, resumed: session.resumed, ...(resume && !session.resumed ? { fresh: true } : {}) });
  if (cancelled) notify("session/cancel", { sessionId });
  const result = await call("session/prompt", { sessionId, prompt: [{ type: "text", text: brief }] });
  flush();
  emit({ type: "done", stopReason: result?.stopReason ?? "end_turn", usage: result?.usage ?? null, final: lastMessage });
} catch (error) {
  flush();
  if (cancelled) emit({ type: "done", stopReason: "cancelled", usage: null, final: lastMessage });
  else emit({ type: "error", message: String(error?.message ?? error).slice(0, 2000) });
  process.exitCode = cancelled ? 0 : 1;
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
