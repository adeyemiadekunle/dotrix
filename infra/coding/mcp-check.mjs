// Whether the MCP servers a coding turn is given (the browser: playwright-mcp) start. Claude Code says when one
// doesn't; fx 0.0.16 and Codex 0.169.0 go on silently without it. So each is started once, asked `initialize`,
// and stopped: fx-acp.mjs passes fx only the ones that answer, and a Codex turn runs this first
// (modules/coding/tools.py `Codex.command`), printing a line for each that didn't:
//
//   node mcp-check.mjs --mcp-config JSON      {"type":"warning","message":"The browser didn't start"}
//
// JSON is Claude Code's format ({"mcpServers": {name: {command, args, env}}}). It never fails the turn: the turn
// goes on without that server, as it would anyway, and the person is told.
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

/** What to say when a server didn't start (shown to people: never names the engine). */
export const notStarted = (name) => (name === "browser" ? "The browser didn't start" : `The ${name} tool didn't start`);

/** Whether a server ({command, args, env: [{name, value}]}) starts and answers `initialize` within 10 s. */
export function answers(server) {
  return new Promise((resolve) => {
    let done = false;
    const env = Object.fromEntries((server.env ?? []).map(({ name, value }) => [name, value]));
    const child = spawn(server.command, server.args ?? [], { stdio: ["pipe", "pipe", "ignore"], env: { ...process.env, ...env } });
    const finish = (ok) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      child.kill("SIGTERM");
      resolve(ok);
    };
    const timer = setTimeout(() => finish(false), 10_000);
    child.on("error", () => finish(false));
    child.on("exit", () => finish(false));
    createInterface({ input: child.stdout }).on("line", (line) => {
      try {
        if (JSON.parse(line)?.id === 1) finish(true);
      } catch {
        // Not a JSON-RPC line: the server's own output.
      }
    });
    child.stdin.on("error", () => finish(false));
    child.stdin.write(
      `${JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "dotrix", version: "1" } } })}\n`,
    );
  });
}

// Run directly (a Codex turn): check each server in the config, say which didn't start, and always exit 0.
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const at = process.argv.indexOf("--mcp-config");
  let servers = {};
  try {
    servers = JSON.parse(process.argv[at + 1] ?? "{}")?.mcpServers ?? {};
  } catch {
    servers = {};
  }
  for (const [name, server] of Object.entries(servers)) {
    const env = Object.entries(server?.env ?? {}).map(([key, value]) => ({ name: key, value: String(value) }));
    const ok = typeof server?.command === "string" && (await answers({ command: server.command, args: (server.args ?? []).map(String), env }));
    if (!ok) process.stdout.write(`${JSON.stringify({ type: "warning", message: notStarted(name) })}\n`);
  }
}
