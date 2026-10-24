import { afterEach, describe, expect, it } from "vitest";

import { desktop, worktreeHere, type DesktopRunner } from "./desktop";

const mine: DesktopRunner = { folder: "/code/pay", workspace: "acme", projectKey: "PAY", state: "coding", runnerId: "r1" };
const run = { location: "local" as const, runner_id: "r1", worktree: "/home/a/.dotrix/worktrees/p/pay-1-abc-1" };
const bridge = { platform: "darwin", runners: {}, worktree: {} };

afterEach(() => {
  delete (globalThis as { dotrixDesktop?: unknown }).dotrixDesktop;
});

describe("worktreeHere", () => {
  it("is nothing in a browser", () => {
    expect(desktop()).toBeNull();
    expect(worktreeHere(run, [mine])).toBeNull();
  });

  it("is a local turn's worktree when one of this computer's runners claimed it", () => {
    (globalThis as { dotrixDesktop?: unknown }).dotrixDesktop = bridge;
    expect(worktreeHere(run, [mine])).toBe(run.worktree);
    expect(worktreeHere({ ...run, runner_id: "someone-elses" }, [mine])).toBeNull();
    expect(worktreeHere({ ...run, location: "cloud" }, [mine])).toBeNull();
    expect(worktreeHere({ ...run, worktree: null }, [mine])).toBeNull();
  });

  it("needs an app with runners (an older desktop app has none)", () => {
    (globalThis as { dotrixDesktop?: unknown }).dotrixDesktop = { platform: "darwin" };
    expect(worktreeHere(run, [mine])).toBeNull();
  });
});
