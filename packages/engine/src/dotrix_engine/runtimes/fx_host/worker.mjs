// Private stdio bridge: no listener, Dotrix tools execute in the parent process.
import { createInterface } from "node:readline";
import { createFxAgent, memory } from "libfx";
import { local } from "libfx/durable-local";

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
const pendingTools = new Map();
let toolSequence = 0;
let agent;
const send = (message) => process.stdout.write(`${JSON.stringify(message)}\n`);

async function callHost(name, args, context) {
  const id = String(++toolSequence);
  return new Promise((resolve, reject) => {
    pendingTools.set(id, { resolve, reject });
    send({ kind: "tool", id, name, args, sessionId: context.sessionId, executionId: context.executionId });
  });
}

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
    if (agent) throw new Error("Already initialized");
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
    agent = createFxAgent(options);
    return { ready: true };
  }
  if (!agent) throw new Error("Runtime is not initialized");
  if (command.op === "new_session") return { sessionId: await agent.newSessionId() };
  if (command.op === "prompt" || command.op === "resume") {
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
    await agent.session(command.sessionId).steer(command.message);
    return { accepted: true };
  }
  if (command.op === "cancel") {
    await agent.session(command.sessionId).cancel();
    return { cancelled: true };
  }
  if (command.op === "close") {
    await agent.close();
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
    if (command.ok) pending.resolve(command.result);
    else pending.reject(new Error("Tool failed."));
    return;
  }
  Promise.resolve(handle(command)).then(
    (result) => send({ kind: "reply", id: command.id, result }),
    () => send({ kind: "reply", id: command.id, error: "libfx operation failed" }),
  );
});
