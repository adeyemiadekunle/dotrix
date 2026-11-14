// The rules for starting a project's app for Kai (node --test, after tsc).
import assert from "node:assert/strict";
import { test } from "node:test";

import { cleanCommand, Lines, readCommands, serverEnv, validPort } from "./devServerRules";

test("a command is one line a person typed", () => {
  assert.equal(cleanCommand("  pnpm install && pnpm dev  "), "pnpm install && pnpm dev");
  for (const bad of ["", "   ", "pnpm dev\nrm -rf ~", "a\0b", "x".repeat(501), 42, null]) assert.equal(cleanCommand(bad), null, String(bad));
});

test("a port is an unprivileged one", () => {
  assert.equal(validPort(5173), 5173);
  for (const bad of [80, 0, 70000, 3000.5, "3000", null]) assert.equal(validPort(bad), null, String(bad));
});

test("saved commands are read by folder, anything malformed left out", () => {
  assert.deepEqual(readCommands(null), {});
  assert.deepEqual(readCommands("not json"), {});
  assert.deepEqual(readCommands("[1]"), {});
  assert.deepEqual(
    readCommands(
      JSON.stringify({
        "/code/pay": { command: "pnpm dev", port: 5173 },
        "/code/web": { command: "npm start", port: 22 },
        "/code/bad": { command: "" },
        "/code/null": null,
      }),
    ),
    { "/code/pay": { command: "pnpm dev", port: 5173 }, "/code/web": { command: "npm start", port: null } },
  );
});

test("the command's environment carries no credentials", () => {
  const env = serverEnv(
    {
      PATH: "/usr/bin",
      HOME: "/home/a",
      ANTHROPIC_API_KEY: "sk-secret",
      DOTRIX_BROWSER_MCP_TOKEN: "t",
      GITHUB_TOKEN: "g",
      AWS_SECRET_ACCESS_KEY: "a",
      PORT: "1",
      Path: "C:\\bin",
    },
    4321,
  );
  assert.deepEqual(env, { PATH: "/usr/bin", HOME: "/home/a", Path: "C:\\bin", PORT: "4321", BROWSER: "none" });
});

test("output is kept as its last lines, without colour codes", () => {
  const lines = new Lines(3);
  lines.push("one\ntwo\r\n\u001b[32mthree\u001b[0m\nfo");
  lines.push("ur");
  assert.equal(lines.tail(), "two\nthree\nfour");
  assert.equal(lines.tail(1), "four");
});
