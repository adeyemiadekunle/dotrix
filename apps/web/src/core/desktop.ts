// The desktop app's bridge (apps/desktop: preload.ts), when the web app runs inside it: its runners
// (the bundled dotrix CLI's `dotrix runner`, one per folder a person picks) and the live worktrees of
// the turns they code. In a browser there's none, and every helper here says so.
import { useEffect, useState } from "react";

import type { CodingRun } from "@/lib/coding";

export interface DesktopRunner {
  folder: string;
  workspace: string;
  projectKey: string;
  state: "starting" | "waiting" | "coding" | "stopped" | "failed";
  runnerId?: string;
  name?: string;
  isolation?: string;
  tools?: string[];
  turn?: { runId: string; issueKey: string; turn: number; worktree: string };
  message?: string;
}

interface WorktreeTree {
  entries: { path: string; status: "added" | "modified" | "deleted" | "unchanged"; size: number | null }[];
  truncated: boolean;
}

interface WorktreeFile {
  path: string;
  status: "added" | "modified" | "deleted" | "unchanged";
  before: string | null;
  after: string | null;
  binary: boolean;
  too_large: boolean;
}

interface Bridge {
  platform: string;
  runners: {
    list(): Promise<DesktopRunner[]>;
    add(workspace: string, projectKey: string): Promise<DesktopRunner | null>;
    remove(folder: string): Promise<void>;
    restart(folder: string): Promise<void>;
    signIn(): Promise<void>;
    onChange(listener: (runners: DesktopRunner[]) => void): () => void;
  };
  worktree: {
    tree(worktree: string): Promise<WorktreeTree>;
    file(worktree: string, file: string): Promise<WorktreeFile>;
    open(worktree: string): Promise<void>;
    reveal(worktree: string): Promise<void>;
  };
}

/** The desktop app's bridge, or null in a browser (or an older app without runners). */
export function desktop(): Bridge | null {
  const found = (globalThis as { dotrixDesktop?: Partial<Bridge> }).dotrixDesktop;
  return found?.runners && found.worktree ? (found as Bridge) : null;
}

/** This computer's runners, kept current (empty in a browser). */
export function useDesktopRunners(): DesktopRunner[] {
  const [runners, setRunners] = useState<DesktopRunner[]>([]);
  useEffect(() => {
    const bridge = desktop();
    if (!bridge) return;
    let live = true;
    void bridge.runners.list().then((list) => live && setRunners(list));
    const off = bridge.runners.onChange(setRunners);
    return () => {
      live = false;
      off();
    };
  }, []);
  return runners;
}

/** A local turn's worktree when it's on this computer (one of its runners claimed it), else null. */
export function worktreeHere(run: Pick<CodingRun, "location" | "runner_id" | "worktree"> | undefined, runners: DesktopRunner[]): string | null {
  if (!run || run.location !== "local" || !run.worktree || !run.runner_id || !desktop()) return null;
  return runners.some((r) => r.runnerId === run.runner_id) ? run.worktree : null;
}
