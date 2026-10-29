// A local protocol experiment, not the platform delegation service.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { once } from "node:events";
import test from "node:test";
import { createFxEngine, createMemoryPersistence } from "libfx";

test("handoff resumes a saved delegation without creating a second batch", { timeout: 30000 }, async () => {
  const server = createServer(async (request, response) => {
    let body = "";
    for await (const chunk of request) body += chunk;
    const input = JSON.parse(body);
    const sawTool = input.messages.some((message) => message.role === "tool");
    const delta = sawTool
      ? { role: "assistant", content: "The specialist completed the review." }
      : {
          role: "assistant",
          tool_calls: [
            {
              index: 0,
              id: "delegate-call-1",
              type: "function",
              function: { name: "delegate_tasks", arguments: JSON.stringify({ brief: "Review the design" }) },
            },
          ],
        };
    const base = { id: "test", object: "chat.completion.chunk", created: 1, model: input.model };
    const chunks = [
      { ...base, choices: [{ index: 0, delta, finish_reason: null }] },
      { ...base, choices: [{ index: 0, delta: {}, finish_reason: sawTool ? "stop" : "tool_calls" }] },
    ];
    response.writeHead(200, { "Content-Type": "text/event-stream" });
    for (const chunk of chunks) response.write(`data: ${JSON.stringify(chunk)}\n\n`);
    response.end("data: [DONE]\n\n");
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const persistence = createMemoryPersistence();
  const batches = new Map();
  const calls = [];
  let started;
  const submitted = new Promise((resolve) => (started = resolve));
  const options = {
    model: "test-model",
    provider: {
      name: "local-test",
      baseUrl: `http://127.0.0.1:${server.address().port}/v1`,
      models: { "test-model": { contextWindow: 128000, supportsToolUse: true } },
    },
    persistence,
    tools: [
      {
        name: "delegate_tasks",
        description: "Submit a specialist task.",
        inputSchema: { type: "object", properties: { brief: { type: "string" } }, required: ["brief"] },
        idempotent: false,
        writes: true,
        async execute(input, context) {
          calls.push(context.executionId);
          if (!batches.has(context.executionId)) batches.set(context.executionId, { input, done: false });
          const batch = batches.get(context.executionId);
          if (batch.done) return { summary: "Specialist completed", status: "completed" };
          started();
          await new Promise((_resolve, reject) => {
            if (context.signal.aborted) return reject(new Error("handoff"));
            context.signal.addEventListener("abort", () => reject(new Error("handoff")), { once: true });
          });
        },
      },
    ],
  };
  let engine;
  try {
    engine = await createFxEngine(options);
    const turn = engine.prompt("Ask the specialist to review the design.");
    const drain = (async () => {
      for await (const event of turn) void event;
    })();
    await submitted;
    turn.cancel({ reason: "handoff" });
    await Promise.allSettled([drain, turn.result]);
    await engine.close();
    engine = undefined;
    assert.equal(batches.size, 1);
    for (const batch of batches.values()) batch.done = true;

    engine = await createFxEngine(options);
    const resumed = engine.resume({
      onAmbiguous(call) {
        if (call.name === "delegate_tasks" && batches.get(call.executionId)?.done) return "rerun";
      },
    });
    let text = "";
    for await (const event of resumed) if (event.type === "text_delta") text += event.delta;
    const outcome = await resumed.result;
    assert.equal(outcome.stopReason, "end_turn");
    assert.match(text, /specialist completed/i);
    assert.equal(batches.size, 1);
    assert.deepEqual(calls, ["delegate-call-1", "delegate-call-1"]);
  } finally {
    if (engine) await engine.close();
    server.close();
    await once(server, "close");
  }
});
