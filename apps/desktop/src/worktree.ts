// A local turn's worktree as it is now, for the web app's Files (Kai's panel) in the desktop app.
// Only folders the runner made, inside ~/.dotrix/worktrees, are ever read or opened (`ownWorktree`).
// No Electron here: the main process (main.ts) exposes these through its checked IPC handlers.
import { execFile } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

/** Only what's inside dotrix's worktrees folder may be read or opened from the web app. */
function worktreesRoot(): string {
  return path.join(os.homedir(), ".dotrix", "worktrees");
}

export interface WorktreeEntry {
  path: string;
  status: "added" | "modified" | "deleted" | "unchanged";
  size: number | null;
}

const MAX_FILE_BYTES = 1_000_000;
const MAX_ENTRIES = 20_000;

/** A worktree the runner made: inside ~/.dotrix/worktrees, after resolving links. Null otherwise. */
export function ownWorktree(tree: unknown): string | null {
  if (typeof tree !== "string" || !path.isAbsolute(tree)) return null;
  try {
    const real = fs.realpathSync(tree);
    const root = fs.realpathSync(worktreesRoot());
    const inside = path.relative(root, real);
    return inside && !inside.startsWith("..") && !path.isAbsolute(inside) ? real : null;
  } catch {
    return null;
  }
}

function git(cwd: string, args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile("git", args, { cwd, maxBuffer: 64 * 1024 * 1024, windowsHide: true }, (error, stdout) => (error ? reject(error) : resolve(String(stdout))));
  });
}

/** Every file in the worktree as it is now, with how it differs from the commit the turn started on. */
export async function worktreeTree(tree: string): Promise<{ entries: WorktreeEntry[]; truncated: boolean }> {
  const tracked = (await git(tree, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])).split("\0").filter(Boolean);
  const status = new Map<string, WorktreeEntry["status"]>();
  for (const row of (await git(tree, ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames"])).split("\0")) {
    if (row.length < 4) continue;
    const code = row.slice(0, 2);
    status.set(row.slice(3), code.includes("?") || code.includes("A") ? "added" : code.includes("D") ? "deleted" : "modified");
  }
  const paths = new Set([...tracked, ...status.keys()]);
  const entries: WorktreeEntry[] = [];
  for (const p of [...paths].sort()) {
    if (p === ".dotrix" || p.startsWith(".dotrix/")) continue;
    let size: number | null = null;
    try {
      size = fs.lstatSync(path.join(tree, p)).size; // a link's own size, never what it points at
    } catch {
      size = null;
    }
    entries.push({ path: p, status: status.get(p) ?? "unchanged", size });
  }
  return { entries: entries.slice(0, MAX_ENTRIES), truncated: entries.length > MAX_ENTRIES };
}

/** One file of the worktree: at the turn's start (HEAD) and now. */
export async function worktreeFile(tree: string, file: unknown) {
  if (typeof file !== "string" || !file || path.isAbsolute(file) || file.split(/[\\/]/).includes("..") || file.includes("\0")) {
    throw new Error("Not a path in the worktree");
  }
  const full = path.join(tree, file);
  if (!path.relative(tree, full) || path.relative(tree, full).startsWith("..")) throw new Error("Not a path in the worktree");
  let before: string | null = null;
  let beforeSize = 0;
  try {
    beforeSize = Number((await git(tree, ["cat-file", "-s", `HEAD:${file}`])).trim());
    before = beforeSize > MAX_FILE_BYTES ? null : await git(tree, ["cat-file", "blob", `HEAD:${file}`]);
  } catch {
    before = null;
    beforeSize = -1;
  }
  let after: string | null = null;
  let afterSize = -1;
  try {
    const real = fs.realpathSync(full);
    if (ownWorktree(real) && fs.statSync(real).isFile()) {
      afterSize = fs.statSync(real).size;
      after = afterSize > MAX_FILE_BYTES ? null : fs.readFileSync(real, "utf8");
    }
  } catch {
    after = null;
  }
  if (beforeSize < 0 && afterSize < 0) throw new Error("No such file in the worktree");
  const tooLarge = Math.max(beforeSize, afterSize) > MAX_FILE_BYTES;
  const binary = !tooLarge && [before, after].some((t) => t?.includes("\0"));
  const status = beforeSize < 0 ? "added" : afterSize < 0 ? "deleted" : before !== after ? "modified" : "unchanged";
  return { path: file, status, before: binary ? null : before, after: binary ? null : after, binary, too_large: tooLarge };
}
