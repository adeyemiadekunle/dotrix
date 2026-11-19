// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import { live } from "../data/live";
import { D } from "../data/store";
import { allowed, approvalModes, canInvite, defaultApproval } from "./can";

type Ws = NonNullable<typeof live.ws>;
const setLive = (permissions: string[], extra: Record<string, unknown> = {}) => {
  live.mode = "live";
  live.ws = { permissions, ...extra } as unknown as Ws;
};
const kind = D().ws.kind;
afterEach(() => {
  live.mode = "demo";
  live.ws = null;
  D().ws.kind = kind;
});

describe("allowed", () => {
  it("lets a live owner do what the API reports and nothing else", () => {
    setLive(["members:manage", "agents:approve"]);
    expect(allowed("members:manage")).toBe(true);
    expect(allowed("workspace:manage")).toBe(false);
  });

  it("denies everything when the live workspace reports nothing", () => {
    live.mode = "live";
    live.ws = null;
    expect(allowed("knowledge:write")).toBe(false);
  });

  it("lets the sample's owners and admins do everything", () => {
    // The sample's signed-in person is whoever D().me names.
    const me = D().members.find((m) => m.id === D().me)!;
    expect(allowed("workspace:manage")).toBe(me.role === "Owner" || me.role === "Admin");
  });
});

describe("canInvite", () => {
  it("needs members:manage in an organisation", () => {
    D().ws.kind = "organisation" as never;
    setLive(["members:manage"]);
    expect(canInvite()).toBe(true);
    setLive([]);
    expect(canInvite()).toBe(false);
  });

  it("is false in a personal workspace", () => {
    D().ws.kind = "personal" as never;
    setLive(["members:manage"]);
    expect(canInvite()).toBe(false);
  });
});

describe("approvalModes", () => {
  it("offers all three on the sample", () => {
    expect(approvalModes()).toEqual(["manual", "accept_edits", "auto"]);
  });

  it("offers only Manual without agents:approve", () => {
    setLive([], { approval_mode_cap: "auto" });
    expect(approvalModes()).toEqual(["manual"]);
  });

  it("stops at the workspace's cap", () => {
    setLive(["agents:approve"], { approval_mode_cap: "accept_edits" });
    expect(approvalModes()).toEqual(["manual", "accept_edits"]);
    setLive(["agents:approve"], { approval_mode_cap: "auto" });
    expect(approvalModes()).toEqual(["manual", "accept_edits", "auto"]);
  });

  it("treats a missing cap as Manual", () => {
    setLive(["agents:approve"]);
    expect(approvalModes()).toEqual(["manual"]);
  });

  it("records today's answer for a cap it doesn't know", () => {
    setLive(["agents:approve"], { approval_mode_cap: "bogus" });
    // indexOf is -1, so slice(0, 0): an empty list, not Manual.
    expect(approvalModes()).toEqual([]);
  });
});

describe("defaultApproval", () => {
  it("uses the workspace's default within your modes, else Manual", () => {
    setLive(["agents:approve"], { approval_mode_cap: "auto", default_approval_mode: "accept_edits" });
    expect(defaultApproval()).toBe("accept_edits");
    setLive(["agents:approve"], { approval_mode_cap: "manual", default_approval_mode: "auto" });
    expect(defaultApproval()).toBe("manual");
  });
});
