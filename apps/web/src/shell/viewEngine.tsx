// Gr8r's filter engine (gr8r-studio/src/shell/view-engine.js): each view's filters (is / is not),
// search, sort, grouping, and the toolbar every task view shares.
import type { ReactNode } from "react";

import { closePop, openPop } from "../core/actions";
import { LABELS, PR, PRIOS, STATUSES, type StatusId } from "../core/constants";
import { Ic } from "../core/icons";
import { DAY, TODAY, diffD, parse } from "../core/utils";
import { D, S, canSee, isOver, mem, pColor, proj, render, save, visibleProjects, type View } from "../data/store";
import type { Filter, Task } from "../data/types";
import { Av, PrIcon, StIcon } from "../ui/helpers";

export interface Opt {
  id: string;
  name: string;
  html?: ReactNode;
}
export const FIELDS: Record<string, { name: string; icon: string; opts: () => Opt[] }> = {
  status: { name: "Status", icon: "circle-dot", opts: () => STATUSES.map((s) => ({ id: s.id, name: s.name, html: <StIcon st={s.id} /> })) },
  assignee: {
    name: "Assignee",
    icon: "user",
    opts: () => [
      { id: "none", name: "Unassigned", html: <Av id={null} cls="sm" tip={false} /> },
      ...D().members.map((m) => ({ id: m.id, name: m.name + (m.id === D().me ? " (you)" : ""), html: <Av id={m.id} cls="sm" tip={false} /> })),
    ],
  },
  priority: { name: "Priority", icon: "signal-high", opts: () => PRIOS.map((p) => ({ id: p.id, name: p.name, html: <PrIcon p={p.id} /> })) },
  due: {
    name: "Due date",
    icon: "calendar",
    opts: () => [
      { id: "overdue", name: "Overdue" },
      { id: "today", name: "Today" },
      { id: "week", name: "Next 7 days" },
      { id: "later", name: "Later" },
      { id: "nodate", name: "No due date" },
    ],
  },
  project: {
    name: "Project",
    icon: "folder",
    opts: () =>
      visibleProjects()
        .filter(canSee)
        .map((p) => ({ id: p.id, name: p.name, html: <span className="pdot" style={{ "--c": pColor(p) } as React.CSSProperties} /> })),
  },
  labels: {
    name: "Labels",
    icon: "tag",
    opts: () => LABELS.map((l) => ({ id: l.id, name: l.name, html: <span className="pdot" style={{ "--c": l.c } as React.CSSProperties} /> })),
  },
  created: {
    name: "Created date",
    icon: "calendar-plus",
    opts: () => [
      { id: "1", name: "Last 24 hours" },
      { id: "7", name: "Last 7 days" },
      { id: "30", name: "Last 30 days" },
    ],
  },
  updated: {
    name: "Updated date",
    icon: "history",
    opts: () => [
      { id: "1", name: "Last 24 hours" },
      { id: "7", name: "Last 7 days" },
      { id: "30", name: "Last 30 days" },
    ],
  },
};

export function viewOf(key: string): View {
  if (!S.views[key])
    S.views[key] = { filters: [], sort: { f: "manual", dir: 1 }, group: "status", q: "", hidden: ["start", "created", "deps"], colW: {}, showDone: true };
  return S.views[key]!;
}
export function matchF(t: Task, f: Filter): boolean {
  if (!f.v || !f.v.length) return true;
  let hit: boolean;
  if (f.f === "labels") hit = f.v.some((v) => t.labels.includes(v));
  else if (f.f === "assignee") hit = f.v.includes(t.assignee || "none");
  else if (f.f === "due") {
    hit = f.v.some((v) => {
      if (v === "nodate") return !t.due;
      if (!t.due) return false;
      const n = diffD(parse(t.due)!, TODAY);
      return v === "overdue" ? isOver(t) : v === "today" ? n === 0 : v === "week" ? n >= 0 && n <= 7 : n > 7;
    });
  } else if (f.f === "created" || f.f === "updated") {
    const ts = f.f === "created" ? t.created : t.updated;
    hit = f.v.some((v) => Date.now() - ts <= +v * DAY);
  } else hit = f.v.includes(String((t as unknown as Record<string, unknown>)[f.f]));
  return f.op === "not" ? !hit : hit;
}
export function applyView(ts: Task[], v: View): Task[] {
  let out = ts.filter((t) => v.filters.every((f) => matchF(t, f)));
  if (v.q) {
    const q = v.q.toLowerCase();
    out = out.filter((t) => t.title.toLowerCase().includes(q) || t.key.toLowerCase().includes(q));
  }
  return sortTasks(out, v.sort);
}
export function sortTasks(ts: Task[], s: { f: string; dir: number }): Task[] {
  const d = s.dir || 1;
  const key: (t: Task) => string | number =
    (
      {
        manual: (t: Task) => t.order,
        title: (t: Task) => t.title.toLowerCase(),
        due: (t: Task) => t.due || "9999",
        start: (t: Task) => t.start || "9999",
        priority: (t: Task) => -PR[t.priority || "none"].w,
        status: (t: Task) => STATUSES.findIndex((x) => x.id === t.status),
        assignee: (t: Task) => mem(t.assignee)?.name || "zzz",
        created: (t: Task) => -t.created,
        updated: (t: Task) => -t.updated,
        estimate: (t: Task) => t.estimate || "zzz",
        project: (t: Task) => proj(t.project)?.name ?? "",
      } as Record<string, (t: Task) => string | number>
    )[s.f] || ((t: Task) => t.order);
  return [...ts].sort((x, y) => {
    const p = key(x);
    const q = key(y);
    return (p > q ? 1 : p < q ? -1 : 0) * d;
  });
}
export interface Group {
  key: string;
  name: string;
  html: ReactNode;
  set?: Partial<Task>;
  tasks: Task[];
}
export function groupTasks(ts: Task[], g: string): Group[] {
  if (g === "none") return [{ key: "all", name: "All tasks", html: null, tasks: ts }];
  let groups: Omit<Group, "tasks">[];
  if (g === "status") groups = STATUSES.map((s) => ({ key: s.id, name: s.name, html: <StIcon st={s.id} />, set: { status: s.id as StatusId } }));
  else if (g === "priority") groups = PRIOS.map((p) => ({ key: p.id, name: p.name, html: <PrIcon p={p.id} />, set: { priority: p.id } }));
  else if (g === "assignee")
    groups = [
      ...D().members.map((m) => ({ key: m.id, name: m.name, html: <Av id={m.id} cls="sm" tip={false} />, set: { assignee: m.id } })),
      { key: "none", name: "Unassigned", html: <Av id={null} cls="sm" tip={false} />, set: { assignee: null } },
    ];
  else if (g === "project")
    groups = visibleProjects()
      .filter(canSee)
      .map((p) => ({ key: p.id, name: p.name, html: <span className="pdot" style={{ "--c": pColor(p) } as React.CSSProperties} />, set: { project: p.id } }));
  else
    groups = [
      { key: "overdue", name: "Overdue" },
      { key: "today", name: "Today" },
      { key: "week", name: "Next 7 days" },
      { key: "later", name: "Later" },
      { key: "nodate", name: "No due date" },
    ].map((x) => ({ ...x, html: <Ic n="calendar" s={14} /> }));
  const out = groups.map((G) => ({
    ...G,
    tasks: ts.filter((t) => {
      if (g === "assignee") return (t.assignee || "none") === G.key;
      if (g === "due") return matchF(t, { f: "due", op: "is", v: [G.key] });
      return String((t as unknown as Record<string, unknown>)[g]) === G.key;
    }),
  }));
  return g === "status" || g === "priority" ? out : out.filter((G) => G.tasks.length);
}

/* ---------- toolbar actions ---------- */
export const viewChange = (key: string, fn: (v: View) => void) => {
  fn(viewOf(key));
  save();
  render();
};
export const clearFilters = (key: string) =>
  viewChange(key, (v) => {
    v.filters = [];
    v.q = "";
    closePop();
  });

export function FilterChips({ k }: { k: string }) {
  const v = viewOf(k);
  if (!v.filters.length) return null;
  return (
    <div className="chipsbar">
      <Ic n="list-filter" s={13} />
      {v.filters.map((f, i) => {
        const F = FIELDS[f.f]!;
        const opts = F.opts();
        const names = f.v.map((id) => opts.find((o) => o.id === id)?.name || id);
        const val = names.length ? (names.length > 2 ? `${names.length} selected` : names.join(", ")) : "any";
        return (
          <span key={i} style={{ display: "contents" }}>
            {i > 0 && <span>and</span>}
            <span className="chip">
              <button onClick={(e) => openPop(e.currentTarget, "fvals", { key: k, i })} style={{ display: "inline-flex", gap: 5, alignItems: "center" }}>
                <Ic n={F.icon} s={12} />
                <b>{F.name}</b> {f.op === "not" ? "is not" : "is"} <span>{val}</span>
              </button>
              <button className="ibtn" aria-label="Remove filter" onClick={() => viewChange(k, (vv) => vv.filters.splice(i, 1))}>
                <Ic n="x" s={12} />
              </button>
            </span>
          </span>
        );
      })}
      <button className="btn btn-sm btn-ghost" onClick={(e) => openPop(e.currentTarget, "filter", { key: k })}>
        <Ic n="plus" s={12} />
        Add
      </button>
      <span className="sp" />
      <button className="btn btn-sm btn-ghost" onClick={() => clearFilters(k)}>
        Clear all
      </button>
    </div>
  );
}

const SORT_NAMES: Record<string, string> = {
  manual: "Manual",
  title: "Title",
  due: "Due date",
  priority: "Priority",
  status: "Status",
  created: "Created",
  updated: "Updated",
  assignee: "Assignee",
  start: "Start date",
  estimate: "Estimate",
  project: "Project",
};
const GROUP_NAMES: Record<string, string> = { status: "Status", priority: "Priority", assignee: "Assignee", project: "Project", due: "Due date", none: "None" };

export function ViewToolbar({ k, group = true, cols = false, extra, right }: { k: string; group?: boolean; cols?: boolean; extra?: ReactNode; right?: ReactNode }) {
  const v = viewOf(k);
  return (
    <>
      <div className="toolbar" role="toolbar">
        <div className="inwrap">
          <Ic n="search" s={13} />
          <input
            className="input search-sm"
            id={`vq-${k}`}
            placeholder="Search tasks"
            value={v.q}
            onChange={(e) => viewChange(k, (vv) => (vv.q = e.target.value))}
            aria-label="Search tasks"
          />
        </div>
        <button className={`btn btn-ghost ${v.filters.length ? "on" : ""}`} onClick={(e) => openPop(e.currentTarget, "filter", { key: k })}>
          <Ic n="list-filter" s={14} />
          Filter
          {v.filters.length > 0 && (
            <span className="badge accent" style={{ height: 16, padding: "0 5px" }}>
              {v.filters.length}
            </span>
          )}
        </button>
        <button className="btn btn-ghost" onClick={(e) => openPop(e.currentTarget, "sort", { key: k })}>
          <Ic n="arrow-up-down" s={14} />
          <span className="hide-m">Sort:</span> {SORT_NAMES[v.sort.f]}
        </button>
        {group && (
          <button className="btn btn-ghost" onClick={(e) => openPop(e.currentTarget, "group", { key: k })}>
            <Ic n="rows-3" s={14} />
            <span className="hide-m">Group:</span> {GROUP_NAMES[v.group]}
          </button>
        )}
        {cols && (
          <button className="btn btn-ghost" onClick={(e) => openPop(e.currentTarget, "cols", { key: k })}>
            <Ic n="columns-3" s={14} />
            Columns
          </button>
        )}
        {extra}
        <span className="sp" />
        {right}
      </div>
      <FilterChips k={k} />
    </>
  );
}
