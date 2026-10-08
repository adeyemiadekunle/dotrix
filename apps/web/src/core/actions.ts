// Gr8r's actions (gr8r-studio/src/actions/actions.js): what clicks and keys do to the workspace.
// They change the seeded data through mutate(); wiring the API turns these into API calls.
import { PR, PSTAT, ST, type ProjectStatusId } from "./constants";
import { TODAY, addD, fmtDate, iso, parse, uid } from "./utils";
import { D, S, canSee, logAct, mem, mutate, proj, render, save, task, visibleProjects, who } from "../data/store";
import type { Project, Task } from "../data/types";
import { toast } from "../ui/toast";

/** Simulated failures for the "couldn't save" state (Help → Simulate offline). */
export function guarded(fn: () => void): boolean {
  if (S.ui.offline) {
    toast("Your changes couldn't be saved. You're offline.", { kind: "err", action: "Try again", onAction: () => guarded(fn) });
    return false;
  }
  mutate(fn);
  return true;
}

/* ---------- tasks ---------- */
export function nextKey(p: Project & { seq?: number }) {
  p.seq = (p.seq || 200) + 1;
  return p.key + "-" + p.seq;
}
export function createTask(f: Partial<Task>): Task {
  const p = proj(f.project) || visibleProjects().find(canSee)!;
  const maxO = Math.max(0, ...D().tasks.map((t) => t.order));
  const t: Task = {
    project: p.id,
    title: "Untitled",
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
    order: maxO + 1,
    fav: false,
    recur: null,
    type: "task",
    ...f,
    id: f.id || uid("t"),
    key: f.key || nextKey(p),
  } as Task;
  t.project = p.id;
  D().tasks.push(t);
  logAct("created", t);
  return t;
}
export const RECUR_DAYS: Record<string, number> = { Daily: 1, Weekly: 7, "Every 2 weeks": 14, Monthly: 30 };

export function applyPatch(t: Task & { prevStatus?: Task["status"] }, patch: Partial<Task>): string[] {
  const msgs: string[] = [];
  for (const k of Object.keys(patch) as (keyof Task)[]) {
    const old = t[k];
    const nv = patch[k];
    if (JSON.stringify(old) === JSON.stringify(nv)) continue;
    (t as unknown as Record<string, unknown>)[k] = nv;
    if (k === "status") {
      if (nv === "done") {
        t.completedAt = Date.now();
        t.prevStatus = old as Task["status"];
        logAct("completed", t);
      } else logAct("moved", t, `from ${ST[old as Task["status"]].name} to ${ST[nv as Task["status"]].name}`);
      if (nv === "done" && t.recur && t.due) {
        const nd = iso(addD(parse(t.due)!, RECUR_DAYS[t.recur] || 7));
        const copy = JSON.parse(JSON.stringify(t)) as Task & { prevStatus?: string };
        delete copy.prevStatus;
        createTask({
          ...copy,
          id: undefined,
          key: undefined,
          status: "todo",
          due: nd,
          start: nd,
          subtasks: t.subtasks.map((s) => ({ ...s, done: false })),
          completedAt: undefined,
          attachments: [],
        });
        msgs.push(`Next “${t.title}” scheduled for ${fmtDate(nd)}`);
      }
    } else if (k === "assignee") logAct("assigned", t, nv ? `to ${who(nv as string)?.name}` : "(unassigned)");
    else if (k === "priority") logAct("changed priority of", t, `to ${PR[nv as Task["priority"]].name}`);
    else if (k === "due") logAct("changed due date of", t, nv ? `to ${fmtDate(nv as string)}` : "(cleared)");
    else if (k === "start") logAct("changed start date of", t, nv ? `to ${fmtDate(nv as string)}` : "(cleared)");
    else if (k === "project") {
      const p = proj(nv as string)!;
      t.key = nextKey(p);
      logAct("moved", t, `to ${p.name}`);
    } else if (k === "labels") logAct("updated labels on", t);
    else if (k === "title") logAct("renamed", t, `to “${nv}”`);
    else if (k === "recur") logAct("set repeat on", t, nv ? (nv as string).toLowerCase() : "off");
    else if (k === "estimate") logAct("estimated", t, (nv as string) || "none");
    else if (k === "deps") logAct("updated dependencies of", t);
    t.updated = Date.now();
  }
  return msgs;
}
export function updateTask(id: string, patch: Partial<Task>) {
  const t = task(id);
  if (!t) return;
  let msgs: string[] = [];
  if (guarded(() => (msgs = applyPatch(t, patch)))) msgs.forEach((m) => toast(m, { kind: "info" }));
}
export function toggleDone(id: string) {
  const t = task(id) as (Task & { prevStatus?: Task["status"] }) | undefined;
  if (!t) return;
  const wasDone = t.status === "done";
  S.ui.pop = null;
  updateTask(t.id, { status: wasDone ? (t.prevStatus && t.prevStatus !== "done" ? t.prevStatus : "todo") : "done" });
  if (!wasDone && !S.ui.offline)
    toast(`Completed “${t.title}”`, { action: "Undo", onAction: () => updateTask(t.id, { status: t.prevStatus || "todo" }) });
}
export function toggleFavTask(id: string) {
  const t = task(id)!;
  mutate(() => {
    t.fav = !t.fav;
  });
  S.ui.pop = null;
  toast(t.fav ? "Added to favorites" : "Removed from favorites", { ms: 1800 });
}
export function toggleFavProj(id: string) {
  const p = proj(id)!;
  mutate(() => {
    p.fav = !p.fav;
  });
  S.ui.pop = null;
  toast(p.fav ? `Added ${p.name} to favorites` : "Removed from favorites", { ms: 1800 });
}
export function setProjectStatus(id: string, v: ProjectStatusId) {
  const pr = proj(id)!;
  mutate(() => {
    pr.status = v;
    D().activity.unshift({ id: uid("a"), by: D().me, verb: "changed status of project", task: null, project: pr.id, at: Date.now(), extra: "to " + PSTAT[v].name });
  });
  S.ui.pop = null;
  toast(`${pr.name} marked ${PSTAT[v].name}`);
}
export function setRole(id: string, role: string) {
  const m = mem(id)!;
  mutate(() => {
    m.role = role as typeof m.role;
  });
  S.ui.pop = null;
  toast(`${m.name} is now ${role === "Admin" ? "an" : "a"} ${role}`);
}

/* ---------- the drawer ---------- */
export function openTask(id: string) {
  const t = task(id);
  if (!t) return;
  if (!canSee(proj(t.project))) {
    toast("You don't have access to that task", { kind: "err" });
    return;
  }
  S.ui.drawerFull = S.prefs.openTasks === "full" || (S.ui.drawerFull && S.ui.drawer === id);
  S.ui.drawer = id;
  S.ui.pop = null;
  S.ui.palette = null;
  S.ui.modals = [];
  S.ui.mention = null;
  S.ui.subOpen = null;
  render();
}
export function closeDrawer() {
  S.ui.drawer = null;
  S.ui.drawerFull = false;
  S.ui.subOpen = null;
  render();
}

/* ---------- sidebar ---------- */
export function toggleSide() {
  S.ui.collapsed = !S.ui.collapsed;
  save();
  render();
}
export function projMove(id: string, d: number) {
  const vis = visibleProjects().map((p) => p.id);
  const i = vis.indexOf(id);
  const j = i + d;
  if (j < 0 || j >= vis.length) return;
  const o = D().projOrder;
  const a = o.indexOf(vis[i]!);
  const b = o.indexOf(vis[j]!);
  [o[a], o[b]] = [o[b]!, o[a]!];
  S.ui.pop = null;
  save();
  render();
  toast(`Moved ${proj(id)!.name} ${d < 0 ? "up" : "down"}`, { ms: 1600 });
}

/* ---------- preferences ---------- */
export function setPref<K extends keyof typeof S.prefs>(k: K, v: (typeof S.prefs)[K]) {
  S.prefs[k] = v;
  save();
  render();
}

export async function copy(text: string, msg = "Link copied") {
  try {
    await navigator.clipboard.writeText(text);
    toast(msg);
  } catch {
    toast("Copy isn't available here — " + text, { kind: "info", ms: 6000 });
  }
}

/* ---------- popovers ---------- */
export type PopType = string;
/** Open a popover under (or over) the element that was clicked; clicking it again closes it. */
export function openPop(el: Element, type: PopType, extra: Record<string, unknown> = {}) {
  const r = el.getBoundingClientRect();
  const p = S.ui.pop;
  if (p && p.type === type && p.id === extra.id && p.key === extra.key && p.field === extra.field && p.i === extra.i) {
    closePop();
    return;
  }
  S.ui.pop = { type, anchor: r, x: r.left, y: r.bottom + 4, top: r.top, w: r.width, q: "", ...extra };
  if (type === "date") {
    const t = task(extra.id as string);
    const field = extra.field as string;
    const cur = field === "subdue" ? t?.subtasks[extra.i as number]?.due : (t as unknown as Record<string, string | null>)?.[field];
    S.ui.pop.m = iso(cur ? parse(cur)! : TODAY);
  }
  render();
}
export function closePop() {
  if (S.ui.pop) {
    S.ui.pop = null;
    render();
  }
}
