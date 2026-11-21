import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { LocalActions, localProfile } from "./localActions";

test("profiles validate each command independently", () => {
  assert.deepEqual(localProfile({ setup: " pnpm install ", tests: "" }), { setup: "pnpm install", tests: "" });
  assert.throws(() => localProfile({ setup: "", tests: "one\ntwo" }), /one line/);
});

test("saved actions use the linked idle worktree and return local output and exit status", async (t) => {
  const home = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "dotrix-local-profile-")));
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));
  t.mock.method(os, "homedir", () => home);
  const repo = path.join(home, "repo");
  const other = path.join(home, "other");
  const tree = path.join(home, ".dotrix", "worktrees", ".sessions", "project", "session");
  const git = (cwd: string, ...args: string[]) => execFileSync("git", args, { cwd, encoding: "utf8" }).trim();
  fs.mkdirSync(repo);
  fs.mkdirSync(other);
  git(repo, "init", "-q", "-b", "main");
  git(other, "init", "-q", "-b", "main");
  git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "Base");
  fs.mkdirSync(path.dirname(tree), { recursive: true });
  git(repo, "worktree", "add", "-q", "--detach", tree, "HEAD");

  const file = path.join(home, "local-code-profiles.json");
  const profile = {
    setup: "",
    tests: `"${process.execPath}" -e "require('node:fs').writeFileSync('marker.txt', 'worktree'); console.log('local output'); process.exit(7)"`,
  };
  new LocalActions(file).save(repo, profile);
  const actions = new LocalActions(file);
  assert.deepEqual(actions.profile(repo), profile);
  actions.save(other, profile);
  await assert.rejects(actions.run(other, tree, "tests"), /different checkout/);
  const marker = `${tree}.active`;
  fs.writeFileSync(marker, "runner");
  await assert.rejects(actions.run(repo, tree, "tests"), /worktree is active/);
  assert.equal(fs.readFileSync(marker, "utf8"), "runner");
  fs.unlinkSync(marker);
  await assert.rejects(actions.run(repo, tree, "setup"), /Save a command/);
  assert.deepEqual(await actions.run(repo, tree, "tests"), { exitCode: 7, output: "local output", timedOut: false });
  assert.equal(fs.existsSync(marker), false);
  assert.equal(fs.existsSync(path.join(repo, "marker.txt")), false);
  assert.equal(fs.readFileSync(path.join(tree, "marker.txt"), "utf8"), "worktree");

  if (process.platform !== "win32") {
    let now = performance.now();
    t.mock.method(performance, "now", () => (now += 2_500));
    const signals: (number | NodeJS.Signals | undefined)[] = [];
    let allowExit = true;
    t.mock.method(process, "kill", (pid: number, signal?: number | NodeJS.Signals) => {
      assert.ok(pid < 0);
      assert.ok(fs.existsSync(marker), "The worktree stays reserved while the process group exists");
      if (allowExit && signal === 0 && signals.includes("SIGKILL")) {
        throw Object.assign(new Error("No such process group"), { code: "ESRCH" });
      }
      signals.push(signal);
      return true;
    });
    assert.equal((await actions.run(repo, tree, "tests")).exitCode, 7);
    assert.deepEqual(signals, ["SIGTERM", 0, "SIGKILL"]);
    assert.equal(fs.existsSync(marker), false);

    allowExit = false;
    await assert.rejects(actions.run(repo, tree, "tests"), /worktree remains reserved/);
    assert.equal(fs.existsSync(marker), true);
    await assert.rejects(actions.run(repo, tree, "tests"), /worktree is active/);
  }
});
