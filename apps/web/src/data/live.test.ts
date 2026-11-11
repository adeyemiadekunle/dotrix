// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryClient } from "@/lib/queryClient";

// The API, as spies: a create stays pending until the test settles it.
const h = vi.hoisted(() => {
  const calls: { method: string; path: string; params: Record<string, string>; body?: unknown }[] = [];
  const creates: { resolve: (key: string | null) => void }[] = [];
  const reply = (data: unknown) => Promise.resolve({ data, error: undefined, response: new Response() });
  const spy = (method: string) => (path: string, init?: { params?: { path?: Record<string, string> }; body?: unknown }) => {
    calls.push({ method, path, params: init?.params?.path ?? {}, body: init?.body });
    if (method === "POST" && path.endsWith("/issues")) {
      return new Promise((resolve) =>
        creates.push({
          resolve: (key) =>
            resolve(
              key
                ? { data: { key, title: "made", description: "" }, error: undefined, response: new Response() }
                : { data: undefined, error: { detail: "no" }, response: new Response(null, { status: 500 }) },
            ),
        }),
      );
    }
    return reply({ key: init?.params?.path?.key ?? "", description: "" });
  };
  return { calls, creates, api: { GET: spy("GET"), POST: spy("POST"), PATCH: spy("PATCH"), PUT: spy("PUT"), DELETE: spy("DELETE") } };
});

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: h.api }));

import type { Task } from "./types";
import { live, taskCreated, taskPatched, taskRanked, taskStarred, tasksDeleted } from "./live";

const PROJECT = "01900000-0000-7000-8000-000000000001";
const sends = () => h.calls.filter((c) => !(c.method === "POST" && c.path.endsWith("/issues")));
const flush = async () => {
  for (let i = 0; i < 20; i++) await Promise.resolve();
  await new Promise((r) => setTimeout(r, 0));
};
const rowsOf = () => queryClient.getQueryData<{ key: string; title: string }[]>(["issues", "workspace", "ws", {}]) ?? [];

function newTask(title = "Fix it"): Task {
  const t = {
    id: "local",
    key: "local",
    project: PROJECT,
    title,
    status: "todo",
    assignee: null,
    priority: "none",
    due: null,
    start: null,
    labels: [],
    subtasks: [],
    attachments: [],
    deps: [],
    desc: "",
    estimate: null,
    created: 0,
    updated: 0,
    order: 1,
    fav: false,
    recur: null,
    type: "task",
  } as unknown as Task;
  void taskCreated(t);
  return t;
}

beforeEach(() => {
  h.calls.length = 0;
  h.creates.length = 0;
  queryClient.clear();
  queryClient.setQueryData(["issues", "workspace", "ws", {}], []);
  Object.assign(live, { mode: "live", ws: { id: "ws" } });
});

describe("changes to a task that is still being created", () => {
  it("sends a rename under the real key once the task exists", async () => {
    const t = newTask();
    await flush();
    expect(t.key.startsWith("new-")).toBe(true);
    const was = t.key;
    t.title = "Renamed";
    taskPatched(t, ["title"]);
    await flush();
    expect(sends()).toHaveLength(0);
    expect(rowsOf().find((r) => r.key === was)?.title).toBe("Renamed");
    h.creates[0]!.resolve("KUN-1");
    await flush();
    expect(sends().map((c) => [c.method, c.params.key, (c.body as { title?: string }).title])).toEqual([["PATCH", "KUN-1", "Renamed"]]);
  });

  it("sends a star under the real key", async () => {
    const t = newTask();
    await flush();
    taskStarred({ ...t, fav: true });
    await flush();
    expect(sends()).toHaveLength(0);
    h.creates[0]!.resolve("KUN-2");
    await flush();
    expect(sends().map((c) => [c.method, c.params.key])).toEqual([["PUT", "KUN-2"]]);
  });

  it("removes a deleted task at once and deletes the real issue afterwards", async () => {
    const t = newTask();
    await flush();
    const was = t.key;
    tasksDeleted([t]);
    await flush();
    expect(rowsOf().some((r) => r.key === was)).toBe(false);
    expect(sends()).toHaveLength(0);
    h.creates[0]!.resolve("KUN-3");
    await flush();
    expect(sends().map((c) => [c.method, c.params.key])).toEqual([["DELETE", "KUN-3"]]);
  });

  it("sends two changes in the order they were made", async () => {
    const t = newTask();
    await flush();
    t.title = "One";
    taskPatched(t, ["title"]);
    t.title = "Two";
    taskPatched(t, ["title"]);
    h.creates[0]!.resolve("KUN-4");
    await flush();
    expect(sends().map((c) => [c.method, c.params.key, (c.body as { title?: string }).title])).toEqual([
      ["PATCH", "KUN-4", "One"],
      ["PATCH", "KUN-4", "Two"],
    ]);
  });

  it("sends nothing, and throws nothing, when the create fails", async () => {
    const t = newTask();
    await flush();
    t.title = "Lost";
    taskPatched(t, ["title"]);
    taskStarred({ ...t, fav: true });
    h.creates[0]!.resolve(null);
    await flush();
    expect(sends()).toHaveLength(0);
  });

  it("never names a provisional key when ranking", async () => {
    const t = newTask();
    const other = newTask("Other");
    await flush();
    taskRanked(t, undefined, other, 5);
    h.creates[0]!.resolve("KUN-5");
    h.creates[1]!.resolve("KUN-6");
    await flush();
    expect(sends().length).toBeGreaterThan(0);
    for (const c of h.calls) {
      expect(JSON.stringify([c.params, c.body])).not.toContain("new-");
    }
    expect(sends().map((c) => [c.params.key, c.body])).toEqual([["KUN-5", { after: "KUN-6" }]]);
  });
});
