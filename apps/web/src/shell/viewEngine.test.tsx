// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { PRIOS, STATUSES } from "../core/constants";
import { DAY, dOff } from "../core/utils";
import { D, people, type View } from "../data/store";
import type { Task } from "../data/types";
import { applyView, groupTasks, sortTasks } from "./viewEngine";

let n = 0;
function task(over: Partial<Task> = {}): Task {
  n += 1;
  return {
    id: `t${n}`,
    key: `X-${n}`,
    project: D().projects[0]!.id,
    title: `Task ${n}`,
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
    created: Date.now(),
    updated: Date.now(),
    order: n,
    fav: false,
    recur: null,
    type: "task",
    ...over,
  } as Task;
}
const ids = (ts: Task[]) => ts.map((t) => t.id);
const groupIds = (ts: Task[], g: string) => Object.fromEntries(groupTasks(ts, g).map((G) => [G.key, ids(G.tasks)]));
const view = (over: Partial<View>): View => ({
  filters: [],
  sort: { f: "manual", dir: 1 },
  group: "none",
  q: "",
  hidden: [],
  colW: {},
  showDone: true,
  ...over,
});
const filtered = (ts: Task[], f: View["filters"][number]) => ids(applyView(ts, view({ filters: [f] })));

describe("groupTasks", () => {
  it("puts every task in one group for none", () => {
    const ts = [task(), task()];
    const g = groupTasks(ts, "none");
    expect(g).toHaveLength(1);
    expect(ids(g[0]!.tasks)).toEqual(ids(ts));
  });

  it("has a group per status, empty ones included", () => {
    const a = task({ status: "todo" });
    const b = task({ status: "done" });
    const g = groupIds([a, b], "status");
    expect(Object.keys(g)).toEqual(STATUSES.map((s) => s.id));
    expect(g.todo).toEqual([a.id]);
    expect(g.done).toEqual([b.id]);
  });

  it("has a group per priority, empty ones included", () => {
    const a = task({ priority: "urgent" });
    const b = task({ priority: "low" });
    const g = groupIds([a, b], "priority");
    expect(Object.keys(g)).toEqual(PRIOS.map((p) => p.id));
    expect(g.urgent).toEqual([a.id]);
    expect(g.low).toEqual([b.id]);
  });

  it("groups by assignee, omitting empty groups", () => {
    const [p1, p2] = people();
    const a = task({ assignee: p1!.id });
    const b = task({ assignee: p2!.id });
    const c = task({ assignee: null });
    const g = groupIds([a, b, c], "assignee");
    expect(g).toEqual({ [p1!.id]: [a.id], [p2!.id]: [b.id], none: [c.id] });
  });

  it.fails("keeps a task assigned to an agent (plan 023)", () => {
    const k = task({ assignee: "agent:kai" });
    const all = Object.values(groupIds([k], "assignee")).flat();
    expect(all).toContain(k.id);
  });

  // Note: "week" is n >= 0 && n <= 7, so a task due today is in both Today and Next 7 days (recorded as is).
  it("groups by due date bucket", () => {
    const over = task({ due: dOff(-3) });
    const today = task({ due: dOff(0) });
    const week = task({ due: dOff(5) });
    const later = task({ due: dOff(20) });
    const none = task({ due: null });
    const g = groupIds([over, today, week, later, none], "due");
    expect(g).toEqual({ overdue: [over.id], today: [today.id], week: [today.id, week.id], later: [later.id], nodate: [none.id] });
  });

  it.fails("keeps a done task whose due date has passed (plan 023)", () => {
    const d = task({ due: dOff(-3), status: "done" });
    const all = Object.values(groupIds([d], "due")).flat();
    expect(all).toContain(d.id);
  });

  it("groups by project", () => {
    const [p1, p2] = D().projects;
    const a = task({ project: p1!.id });
    const b = task({ project: p2!.id });
    const g = groupIds([a, b], "project");
    expect(g[p1!.id]).toEqual([a.id]);
    expect(g[p2!.id]).toEqual([b.id]);
  });
});

describe("sortTasks", () => {
  const sorted = (ts: Task[], f: string, dir = 1) => ids(sortTasks(ts, { f, dir }));

  it("sorts titles case-insensitively", () => {
    const b = task({ title: "banana" });
    const a = task({ title: "Apple" });
    const c = task({ title: "cherry" });
    expect(sorted([c, b, a], "title")).toEqual([a.id, b.id, c.id]);
  });

  it("sorts by due date with undated tasks last", () => {
    const none = task({ due: null });
    const late = task({ due: dOff(9) });
    const soon = task({ due: dOff(1) });
    expect(sorted([none, late, soon], "due")).toEqual([soon.id, late.id, none.id]);
  });

  it("sorts the most urgent priority first", () => {
    const low = task({ priority: "low" });
    const urgent = task({ priority: "urgent" });
    const none = task({ priority: "none" });
    expect(sorted([low, none, urgent], "priority")).toEqual([urgent.id, low.id, none.id]);
  });

  it("sorts created and updated newest first", () => {
    const old = task({ created: Date.now() - 5 * DAY, updated: Date.now() - 5 * DAY });
    const fresh = task({ created: Date.now(), updated: Date.now() });
    expect(sorted([old, fresh], "created")).toEqual([fresh.id, old.id]);
    expect(sorted([old, fresh], "updated")).toEqual([fresh.id, old.id]);
  });

  it("reverses with dir -1", () => {
    const a = task({ title: "a" });
    const b = task({ title: "b" });
    expect(sorted([a, b], "title", -1)).toEqual([b.id, a.id]);
  });

  it.fails("sorts estimates as numbers (plan 023)", () => {
    const ten = task({ estimate: "10" });
    const two = task({ estimate: "2" });
    expect(sorted([ten, two], "estimate")).toEqual([two.id, ten.id]);
  });
});

// matchF isn't exported, so its branches are tested through applyView's filters.
describe("filters (matchF through applyView)", () => {
  it("matches no due date", () => {
    const none = task({ due: null });
    const dated = task({ due: dOff(2) });
    expect(filtered([none, dated], { f: "due", op: "is", v: ["nodate"] })).toEqual([none.id]);
  });

  it("matches today, the next 7 days, later and overdue", () => {
    const over = task({ due: dOff(-2) });
    const doneOver = task({ due: dOff(-2), status: "done" });
    const today = task({ due: dOff(0) });
    const week = task({ due: dOff(7) });
    const later = task({ due: dOff(8) });
    const all = [over, doneOver, today, week, later];
    expect(filtered(all, { f: "due", op: "is", v: ["today"] })).toEqual([today.id]);
    expect(filtered(all, { f: "due", op: "is", v: ["week"] })).toEqual([today.id, week.id]);
    expect(filtered(all, { f: "due", op: "is", v: ["later"] })).toEqual([later.id]);
    expect(filtered(all, { f: "due", op: "is", v: ["overdue"] })).toEqual([over.id]);
  });

  it("matches created within N days", () => {
    const fresh = task({ created: Date.now() - 1000 });
    const old = task({ created: Date.now() - 10 * DAY });
    expect(filtered([fresh, old], { f: "created", op: "is", v: ["7"] })).toEqual([fresh.id]);
    expect(filtered([fresh, old], { f: "created", op: "is", v: ["30"] })).toEqual([fresh.id, old.id]);
  });

  it("matches updated within N days", () => {
    const fresh = task({ updated: Date.now() - 1000 });
    const old = task({ updated: Date.now() - 10 * DAY });
    expect(filtered([fresh, old], { f: "updated", op: "is", v: ["1"] })).toEqual([fresh.id]);
  });

  it("matches labels", () => {
    const a = task({ labels: ["bug"] });
    const b = task({ labels: ["design"] });
    expect(filtered([a, b], { f: "labels", op: "is", v: ["bug"] })).toEqual([a.id]);
  });

  it("matches status is and is not", () => {
    const a = task({ status: "todo" });
    const b = task({ status: "done" });
    expect(filtered([a, b], { f: "status", op: "is", v: ["done"] })).toEqual([b.id]);
    expect(filtered([a, b], { f: "status", op: "not", v: ["done"] })).toEqual([a.id]);
  });

  it("matches assignee is and is not, with none for unassigned", () => {
    const [p1] = people();
    const a = task({ assignee: p1!.id });
    const b = task({ assignee: null });
    expect(filtered([a, b], { f: "assignee", op: "is", v: [p1!.id] })).toEqual([a.id]);
    expect(filtered([a, b], { f: "assignee", op: "is", v: ["none"] })).toEqual([b.id]);
    expect(filtered([a, b], { f: "assignee", op: "not", v: [p1!.id] })).toEqual([b.id]);
  });

  it("matches everything for a filter with no values", () => {
    const a = task();
    expect(filtered([a], { f: "status", op: "is", v: [] })).toEqual([a.id]);
  });
});
