// Test helper: a low-level fx engine whose delegation tool is driven by a Python host.
// Its journal is in memory; this does not implement process recovery.
import { once } from "node:events";
import { createServer } from "node:http";
import { createInterface } from "node:readline";
import { createFxEngine, createMemoryPersistence } from "libfx";

const commands = createInterface({ input: process.stdin, crlfDelay: Infinity })[Symbol.asyncIterator]();
const send = (event) => process.stdout.write(`${JSON.stringify(event)}\n`);
const receive = async () => {
  const line = await commands.next();
  if (line.done) throw new Error("Host closed the probe");
  return JSON.parse(line.value);
};

const server = createServer(async (request, response) => {
  let body = "";
  for await (const chunk of request) body += chunk;
  const input = JSON.parse(body);
  const toolResult = input.messages.find((message) => message.role === "tool");
  const delta = toolResult
    ? { role: "assistant", content: `Specialist result: ${toolResult.content}` }
    : {
        role: "assistant",
        tool_calls: [
          {
            index: 0,
            id: "delegation-call-1",
            type: "function",
            function: { name: "delegate_tasks", arguments: JSON.stringify({ brief: "Review the design" }) },
          },
        ],
      };
  const base = { id: "test", object: "chat.completion.chunk", created: 1, model: input.model };
  response.writeHead(200, { "Content-Type": "text/event-stream" });
  response.write(`data: ${JSON.stringify({ ...base, choices: [{ index: 0, delta, finish_reason: null }] })}\n\n`);
  response.write(`data: ${JSON.stringify({ ...base, choices: [{ index: 0, delta: {}, finish_reason: toolResult ? "stop" : "tool_calls" }] })}\n\n`);
  response.end("data: [DONE]\n\n");
});
server.listen(0, "127.0.0.1");
await once(server, "listening");

let engine;
let activeTurn;
let executionId;
const options = {
  model: "test-model",
  provider: {
    name: "local-test",
    baseUrl: `http://127.0.0.1:${server.address().port}/v1`,
    models: { "test-model": { contextWindow: 128000, supportsToolUse: true } },
  },
  persistence: createMemoryPersistence(),
  tools: [
    {
      name: "delegate_tasks",
      description: "Submit a specialist task.",
      inputSchema: { type: "object", properties: { brief: { type: "string" } }, required: ["brief"] },
      idempotent: false,
      writes: true,
      async execute(input, context) {
        executionId ??= context.executionId;
        send({ kind: "delegate", executionId: context.executionId, input });
        const command = await receive();
        if (command.action === "result") return command.result;
        if (command.action !== "suspend") throw new Error("Unexpected host response");
        setImmediate(() => activeTurn.cancel({ reason: "handoff" }));
        await new Promise((_resolve, reject) => {
          if (context.signal.aborted) return reject(new Error("handoff"));
          context.signal.addEventListener("abort", () => reject(new Error("handoff")), { once: true });
        });
      },
    },
  ],
};

try {
  engine = await createFxEngine(options);
  activeTurn = engine.prompt("Ask the specialist to review the design.");
  const drain = (async () => {
    for await (const event of activeTurn) void event;
  })();
  await Promise.allSettled([drain, activeTurn.result]);
  await engine.close();
  engine = undefined;
  send({ kind: "suspended" });
  if ((await receive()).action !== "resume") throw new Error("Expected resume");

  engine = await createFxEngine(options);
  activeTurn = engine.resume({
    onAmbiguous(call) {
      if (call.name === "delegate_tasks" && call.executionId === executionId) return "rerun";
    },
  });
  let text = "";
  for await (const event of activeTurn) if (event.type === "text_delta") text += event.delta;
  const result = await activeTurn.result;
  send({ kind: "finished", stopReason: result.stopReason, text });
} finally {
  if (engine) await engine.close();
  server.close();
  await once(server, "close");
  await commands.return();
}
