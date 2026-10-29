// Private stdio bridge: no listener, Dotrix tools execute in the parent process.
import { createInterface } from "node:readline";
import { createRequire } from "node:module";
import { createFxAgent, createFxEngine, FxFencedError, memory } from "libfx";
import { local } from "libfx/durable-local";

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
const pendingTools = new Map();
const pendingStorage = new Map();
let toolSequence = 0;
let storageSequence = 0;
let agent;
let engine;
let activeTurn;
let handedOff;
let engineSession;
let restoredAnswers = new Map();
let restoredJournal = false;
const send = (message) => process.stdout.write(`${JSON.stringify(message)}\n`);

async function callHost(name, args, context) {
  const id = String(++toolSequence);
  const reply = await new Promise((resolve, reject) => {
    pendingTools.set(id, { resolve, reject });
    send({ kind: "tool", id, name, args, sessionId: context.sessionId, executionId: context.executionId });
  });
  if (!reply.handoff) return reply.result;
  if (!engine || !activeTurn || name !== "delegate_tasks") throw new Error("Invalid handoff");
  handedOff = context.executionId;
  setImmediate(() => activeTurn.cancel({ reason: "handoff" }));
  await new Promise((_resolve, reject) => {
    if (context.signal.aborted) return reject(new Error("handoff"));
    context.signal.addEventListener("abort", () => reject(new Error("handoff")), { once: true });
  });
}

async function callStorage(op, payload = {}) {
  const id = String(++storageSequence);
  return new Promise((resolve, reject) => {
    pendingStorage.set(id, { resolve, reject });
    send({ kind: "storage", id, op, ...payload });
  });
}

const encode = (data) => Buffer.from(data).toString("base64");
const decode = (data) => new Uint8Array(Buffer.from(data, "base64"));

// libfx 0.0.15's low-level engine deliberately omits output for an already
// completed turn. Its v1 journal is the only durable source of that output.
// Keep this compatibility reader isolated and fail closed on a new format.
function committedAnswers(records) {
  const turns = new Map();
  const answers = new Map();
  for (const record of records) {
    const stored = JSON.parse(Buffer.from(record.data, "base64").toString("utf8"));
    if (stored?.format !== "libfx-journal-v1" || !Array.isArray(stored.events)) throw new Error("Unsupported fx journal");
    for (const event of stored.events) {
      if (event?.type === "turn_progress" && typeof event.turnId === "string") turns.set(event.turn, event.turnId);
      if (event?.type === "turn_committed" && turns.has(event.turn)) {
        if (event.data?.kind !== "assistant") continue;
        if (typeof event.data?.assistant !== "string") throw new Error("Unsupported fx turn result");
        answers.set(turns.get(event.turn), event.data.assistant);
      }
    }
  }
  return answers;
}

const persistence = {
  async load() {
    const result = await callStorage("load");
    restoredJournal = result.records.length > 0 || result.checkpoint != null;
    restoredAnswers = committedAnswers(result.records);
    return {
      ...(result.checkpoint ? { checkpoint: { through: result.checkpoint.through, data: decode(result.checkpoint.data) } } : {}),
      journal: result.records.map((record) => ({ cursor: record.cursor, data: decode(record.data) })),
    };
  },
  async append({ expected, idempotencyKey, data, barrier }) {
    return callStorage("append", { expected, idempotencyKey, data: encode(data), barrier });
  },
  async saveCheckpoint({ through, data }) {
    await callStorage("checkpoint", { through, data: encode(data) });
  },
};

async function storedTurn(session, messageId) {
  // A settled retry's turn view only returns turn_end; recover its prior output
  // from the session stream. The result's `repeated` flag distinguishes replay.
  const reader = session.stream(0).getReader();
  const decoder = new TextDecoder();
  let buffered = "";
  let text = "";
  const tools = [];
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) throw new Error("Stored turn output was not found");
      buffered += decoder.decode(value, { stream: true });
      for (let index = buffered.indexOf("\n"); index >= 0; index = buffered.indexOf("\n")) {
        const line = buffered.slice(0, index);
        buffered = buffered.slice(index + 1);
        if (!line) continue;
        const event = JSON.parse(line);
        if (event.messageId !== messageId) continue;
        if (event.type === "text_delta") text += event.delta;
        if (event.type === "tool_start") tools.push(event.name);
        if (event.type === "turn_end") return { text, tools };
      }
    }
  } finally {
    void reader.cancel().catch(() => {});
  }
}

async function handle(command) {
  if (command.op === "init") {
    if (agent || engine) throw new Error("Already initialized");
    const options = {
      name: command.name,
      instructions: command.instructions,
      model: command.effort ? { id: command.model, effort: command.effort } : command.model,
      durability: command.localDir ? local({ dir: command.localDir }) : memory(),
      tools: command.tools.map((tool) => ({
        name: tool.name,
        description: tool.description,
        inputSchema: tool.inputSchema,
        idempotent: tool.idempotent,
        writes: tool.writes,
        execute: (args, context) => callHost(tool.name, args, context),
      })),
    };
    if (command.baseUrl) {
      options.provider = {
        name: "dotrix-host",
        baseUrl: command.baseUrl,
        models: { [command.model]: { contextWindow: command.contextWindow, supportsToolUse: true } },
      };
      if (command.apiKey) options.credentials = async () => ({ apiKey: command.apiKey });
    } else if (command.apiKey) options.apiKey = command.apiKey;
    if (command.persistence) {
      const version = createRequire(import.meta.url)("./node_modules/libfx/package.json").version;
      if (version !== "0.0.15") throw new Error("Unsupported libfx journal version");
      engineSession = command.sessionId;
      delete options.name;
      delete options.durability;
      options.sessionId = engineSession;
      options.persistence = persistence;
      // The host limits a journal to 8 MiB; retain its full record history so
      // the pinned compatibility reader can recover a completed turn's text.
      options.checkpointAfterBytes = 16 * 1024 * 1024;
      engine = await createFxEngine(options);
    } else {
      agent = createFxAgent(options);
    }
    return { ready: true };
  }
  if (!agent && !engine) throw new Error("Runtime is not initialized");
  if (command.op === "new_session") return { sessionId: engine ? engineSession : await agent.newSessionId() };
  if (command.op === "prompt" || command.op === "resume") {
    if (engine) {
      if (command.sessionId !== engineSession || activeTurn) throw new Error("Invalid engine session");
      handedOff = undefined;
      const onAmbiguous = (call) => ((command.rerunTools ?? []).includes(call.name) ? "rerun" : undefined);
      activeTurn =
        command.op === "prompt" ? engine.prompt(command.message, { turnId: command.messageId ?? undefined, onAmbiguous }) : engine.resume({ onAmbiguous });
      if (!activeTurn) {
        const text = restoredAnswers.get(command.messageId);
        if (typeof text !== "string") throw new Error("No recoverable turn");
        return { text, tools: [], stopReason: "end_turn", usage: null, repeated: true, messageId: command.messageId };
      }
      const settled = activeTurn.result.then(
        (value) => ({ value }),
        (error) => ({ error }),
      );
      let text = "";
      const tools = [];
      try {
        try {
          for await (const event of activeTurn) {
            if (event.type === "text_delta") {
              text += event.delta;
              send({ kind: "event", id: command.id, event: { type: "text_delta", text: event.delta } });
            } else if (event.type === "tool_start" || event.type === "tool_end") {
              if (event.type === "tool_start") tools.push(event.name);
              send({ kind: "event", id: command.id, event: { type: event.type, tool: event.name } });
            }
          }
        } catch (error) {
          if (!handedOff) throw error;
        }
        const outcome = await settled;
        if (outcome.error && !handedOff) throw outcome.error;
        const result = outcome.value;
        let repeated = false;
        if (!handedOff && result.stopReason === "end_turn" && !text) {
          if (!restoredAnswers.has(command.messageId)) throw new Error("No recoverable completed output");
          text = restoredAnswers.get(command.messageId);
          repeated = true;
        }
        return {
          text,
          tools,
          stopReason: handedOff ? "handoff" : result.stopReason,
          // Recovery may omit usage incurred before handoff or process death.
          usage: repeated || restoredJournal ? null : (result?.usage ?? null),
          repeated,
          handoff: handedOff ?? null,
          messageId: command.messageId ?? null,
        };
      } finally {
        activeTurn = undefined;
      }
    }
    const session = agent.session(command.sessionId);
    const turn = command.op === "prompt" ? session.prompt(command.message, command.messageId ? { messageId: command.messageId } : {}) : session.resume();
    const accepted = await turn.accepted;
    send({ kind: "event", id: command.id, event: { type: "turn_accepted", messageId: accepted.messageId } });
    let text = "";
    let tools = [];
    for await (const event of turn) {
      if (event.type === "text_delta") {
        text += event.delta;
        send({ kind: "event", id: command.id, event: { type: "text_delta", text: event.delta } });
      } else if (event.type === "tool_start" || event.type === "tool_end") {
        if (event.type === "tool_start") tools.push(event.name);
        send({ kind: "event", id: command.id, event: { type: event.type, tool: event.name } });
      }
    }
    const result = await turn.result;
    if (result.repeated && result.stopReason !== "error") {
      ({ text, tools } = await storedTurn(session, result.messageId));
    }
    return {
      text,
      tools,
      stopReason: result.stopReason,
      usage: result.usage ?? null,
      messageId: result.messageId ?? accepted.messageId,
      repeated: result.repeated === true,
    };
  }
  if (command.op === "steer") {
    if (engine) {
      if (!activeTurn || command.sessionId !== engineSession) throw new Error("No active turn");
      await activeTurn.steer(command.message);
    } else await agent.session(command.sessionId).steer(command.message);
    return { accepted: true };
  }
  if (command.op === "cancel") {
    if (engine) activeTurn?.cancel();
    else await agent.session(command.sessionId).cancel();
    return { cancelled: true };
  }
  if (command.op === "close") {
    if (engine) await engine.close();
    else await agent.close();
    engine = undefined;
    agent = undefined;
    return { closed: true };
  }
  throw new Error("Unknown operation");
}

input.on("line", (line) => {
  let command;
  try {
    command = JSON.parse(line);
  } catch {
    return;
  }
  if (command.op === "tool_reply") {
    const pending = pendingTools.get(command.id);
    if (!pending) return;
    pendingTools.delete(command.id);
    if (command.ok) pending.resolve({ result: command.result, handoff: command.handoff === true });
    else pending.reject(new Error("Tool failed."));
    return;
  }
  if (command.op === "storage_reply") {
    const pending = pendingStorage.get(command.id);
    if (!pending) return;
    pendingStorage.delete(command.id);
    if (command.ok) pending.resolve(command.result);
    else pending.reject(command.fenced ? new FxFencedError("Journal advanced") : new Error("Journal failed"));
    return;
  }
  Promise.resolve(handle(command)).then(
    (result) => send({ kind: "reply", id: command.id, result }),
    () => send({ kind: "reply", id: command.id, error: "libfx operation failed" }),
  );
});
