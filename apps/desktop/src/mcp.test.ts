// The app's MCP server for Kai's local tools (node --test, after tsc).
import assert from "node:assert/strict";
import { after, before, test } from "node:test";

import { McpServer, type ToolSet } from "./mcp";

const tools: ToolSet = {
  list: (caller) => [
    { name: "echo", description: "Says it back", inputSchema: { type: "object", properties: { text: { type: "string" } } } },
    ...(caller === "/b" ? [{ name: "who", description: "Says who calls", inputSchema: { type: "object" } }] : []),
  ],
  call: async (name, args, caller) => {
    if (name === "who") return [{ type: "text", text: caller }];
    if (args.text === "fail") throw new Error("It failed");
    return [{ type: "text", text: String(args.text) }];
  },
};
const server = new McpServer("test", "1.0.0", tools);
const token = server.tokenFor("/a");
before(() => server.start());
after(() => server.stop());

const post = (body: unknown, headers: Record<string, string> = {}, as = token) =>
  fetch(server.url!, {
    method: "POST",
    headers: { authorization: `Bearer ${as}`, "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });

test("it answers only requests with its token, and never a web page", async () => {
  assert.match(server.url!, /^http:\/\/127\.0\.0\.1:\d+\/mcp$/);
  assert.equal((await post({ jsonrpc: "2.0", id: 1, method: "ping" }, { authorization: "Bearer wrong" })).status, 401);
  assert.equal((await fetch(server.url!, { method: "POST", body: "{}" })).status, 401);
  assert.equal((await post({ jsonrpc: "2.0", id: 1, method: "ping" }, { origin: "https://evil.example" })).status, 403);
  assert.equal((await fetch(server.url!, { headers: { authorization: `Bearer ${token}` } })).status, 405);
});

test("it lists and calls tools", async () => {
  const hello = (await (await post({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-03-26" } })).json()) as {
    result: { protocolVersion: string; capabilities: unknown };
  };
  assert.equal(hello.result.protocolVersion, "2025-03-26");
  assert.deepEqual(hello.result.capabilities, { tools: {} });
  assert.equal((await post({ jsonrpc: "2.0", method: "notifications/initialized" })).status, 202);
  const listed = (await (await post({ jsonrpc: "2.0", id: 2, method: "tools/list" })).json()) as { result: { tools: { name: string }[] } };
  assert.deepEqual(
    listed.result.tools.map((tool) => tool.name),
    ["echo"],
  );
  const called = (await (await post({ jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "echo", arguments: { text: "hi" } } })).json()) as {
    result: unknown;
  };
  assert.deepEqual(called.result, { content: [{ type: "text", text: "hi" }] });
});

test("a tool's failure, or an unknown tool, is told as the tool's error", async () => {
  for (const params of [
    { name: "echo", arguments: { text: "fail" } },
    { name: "nope", arguments: {} },
  ]) {
    const answer = (await (await post({ jsonrpc: "2.0", id: 4, method: "tools/call", params })).json()) as { result: { isError: boolean } };
    assert.equal(answer.result.isError, true);
  }
  const unknown = (await (await post({ jsonrpc: "2.0", id: 5, method: "resources/list" })).json()) as { error: { code: number } };
  assert.equal(unknown.error.code, -32601);
});

test("each caller has a token of its own, and the tools know who calls", async () => {
  assert.equal(server.tokenFor("/a"), token);
  const other = server.tokenFor("/b");
  assert.notEqual(other, token);
  const listed = (await (await post({ jsonrpc: "2.0", id: 6, method: "tools/list" }, {}, other)).json()) as { result: { tools: { name: string }[] } };
  assert.deepEqual(
    listed.result.tools.map((tool) => tool.name),
    ["echo", "who"],
  );
  const who = (await (await post({ jsonrpc: "2.0", id: 7, method: "tools/call", params: { name: "who", arguments: {} } }, {}, other)).json()) as {
    result: { content: { text: string }[] };
  };
  assert.equal(who.result.content[0]!.text, "/b");
  // A tool another caller is offered isn't this one's.
  const refused = (await (await post({ jsonrpc: "2.0", id: 8, method: "tools/call", params: { name: "who", arguments: {} } })).json()) as {
    result: { isError: boolean };
  };
  assert.equal(refused.result.isError, true);
});
