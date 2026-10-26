// Store for React: one state (the seeded workspace, your
// preferences, each view's filters, and UI state such as the open drawer or popover), saved in
// this browser. Components read it with useStudio() and re-render on any change
// render loop; changes go through mutate(). Wiring the API replaces the seed and the actions,
// not the screens.
import { useSyncExternalStore } from "react";

import { PCOLORS } from "../core/constants";
import { TODAY, diffD, iso, parse, uid } from "../core/utils";
import { AGENTS, CODING_TOOLS } from "./seed-dotrix";
import { seed } from "./seed";
import type { Data, Filter, Project, Task } from "./types";

const STORE_KEY = "dotrix.studio.v2"; // v2: the seeded workspace is Dotrix
export const DEFAULT_PREFS = {
  theme: "system" as "system" | "light" | "dark",
  accent: "graphite",
  side: "comfortable",
  density: "comfortable",
  weekStart: 1,
  dateFmt: "MMM d",
  tz: "(GMT-07:00) Pacific Time",
  motion: "system",
  home: "home",
  openTasks: "drawer" as "drawer" | "full",
  name: "Tanjim Islam",
  title: "Head of Product",
  /** the agents panel on the right, on wide screens */
  agentsPanel: true,
};
export type Prefs = typeof DEFAULT_PREFS;

export interface View {
  filters: Filter[];
  sort: { f: string; dir: number };
  group: string;
  q: string;
  hidden: string[];
  colW: Record<string, number>;
  showDone: boolean;
}

export type Pop = { type: string; anchor: DOMRect; [k: string]: unknown } | null;
export type Modal = { type: string; [k: string]: unknown };

interface Saved {
  data: Data;
  prefs: Prefs;
  views: Record<string, View>;
  collapsed: boolean;
}

function load(): Saved | null {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) {
      const j = JSON.parse(raw) as Saved;
      if (j?.data?.tasks && j.data.threads) return j;
    }
  } catch {
    /* storage blocked or corrupt: start from the seed */
  }
  return null;
}
const saved = load();

export const S = {
  data: saved?.data ?? seed(),
  prefs: { ...DEFAULT_PREFS, ...(saved?.prefs ?? {}) } as Prefs,
  views: saved?.views ?? ({} as Record<string, View>),
  ui: {
    collapsed: Boolean(saved?.collapsed),
    mnav: false,
    expanded: { p1: true } as Record<string, boolean>,
    drawer: null as string | null,
    drawerFull: false,
    drawerTab: "comments" as "comments" | "activity",
    modals: [] as Modal[],
    pop: null as Pop,
    palette: null as null | { q: string; mode: "cmd" | "search" | "ws"; scope: string; hl: number },
    offline: false,
    sel: new Set<string>(),
    composer: null as null | { key: string; group: string },
    editCell: null as null | { id: string; field: string },
    collapsedGroups: {} as Record<string, boolean>,
    collapsedCols: {} as Record<string, boolean>,
    drafts: {} as Record<string, string>,
    subOpen: null as null | { tid: string; sid: string },
    mention: null as null | { tid: string; q: string },
    // each page's own controls (kept in the store, so they survive navigating away)
    calDate: iso(TODAY),
    fileQ: "",
    fileType: "all",
    fileSort: "date",
    fileView: "grid" as "grid" | "list",
    projView: "grid" as "grid" | "list" | "table",
    projQ: "",
    projStatus: "all",
    projSort: "recent",
    inboxCat: "all",
    inboxUnread: false,
    inboxSel: null as string | null,
    myTab: "mine" as "mine" | "starred" | "archived",
    agentSel: null as string | null,
    // dotrix: chat
    chatBusy: null as string | null,
    chatAgent: "auto",
    chatModel: "Gemini 3.8 Flash",
    chatQ: "",
    showArchivedSessions: false, // Chat's Code tab lists its archived sessions instead
    searchQ: "",
    searchCat: "all",
    myView: "list" as "list" | "calendar",
    membersTab: "members",
    memQ: "",
    memRole: "all",
    memTab: "assigned",
    actFilter: "all",
    actWho: "all",
    settings: "profile",
    /** the agents panel as a sheet, on narrower screens */
    agentsSheet: false,
    /** corner notices closed this session (by key) */
    noticesShut: [] as string[],
  },
};

/* ---------- change and subscribe ---------- */
let version = 0;
const listeners = new Set<() => void>();
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
let saveTimer: ReturnType<typeof setTimeout> | undefined;
/** What this browser keeps: the demo's data (a real workspace's lives in the API; data/live.ts). */
const persist = { data: (): Data => S.data };

/** A live workspace's data, mirrored in from the TanStack queries by the StoreBridge — null on the
 *  demo, so S.data keeps the demo's seed untouched while you're signed in. */
let liveData: Data | null = null;
export function setLiveData(d: Data | null) {
  liveData = d;
}
function writeNow() {
  clearTimeout(saveTimer);
  saveTimer = undefined;
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({ data: persist.data(), prefs: S.prefs, views: S.views, collapsed: S.ui.collapsed }));
  } catch {
    /* storage full or blocked: keep working in memory */
  }
}
export function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(writeNow, 150);
}
// A change made just before a reload or navigating away is still written.
if (typeof window !== "undefined") addEventListener("pagehide", () => saveTimer !== undefined && writeNow());
/** Re-render whoever reads the store (UI-only changes: popovers, selection, the drawer). */
export function render() {
  version++;
  for (const l of listeners) l();
}
/** Change the workspace's data: kept in this browser, then re-rendered. */
export function mutate(fn: () => void) {
  fn();
  save();
  render();
}
/** The store, re-rendering this component on every change. */
export function useStudio() {
  useSyncExternalStore(subscribe, () => version);
  return S;
}
/** Start over from the seed (Settings → Reset demo data). */

/* ---------- lookups ---------- */
export const D = () => liveData ?? S.data;
export const me = () => D().members.find((m) => m.id === D().me)!;
export const mem = (id: string | null | undefined) => D().members.find((m) => m.id === id);
/** People who can be assigned, mentioned, or put in a team: not deactivated, and not an invite still pending in a real workspace (no account yet). */
export const people = () => D().members.filter((m) => m.status !== "deactivated" && !m.id.startsWith("invite:"));
export const proj = (id: string | null | undefined) => D().projects.find((p) => p.id === id);
export const projByKey = (key: string | undefined) => D().projects.find((p) => p.key.toLowerCase() === key?.toLowerCase());
export const task = (id: string | null | undefined) => D().tasks.find((t) => t.id === id);

export const pColor = (p: Project | undefined) => PCOLORS[p?.color ?? "slate"] ?? PCOLORS.slate!;
export const visibleProjects = () =>
  D()
    .projOrder.map(proj)
    .filter((p): p is Project => Boolean(p))
    .filter((p) => !p.archived);
export const canSee = (p: Project | undefined) => Boolean(p) && (!p!.private || p!.members.includes(D().me));
export const tasksOf = (pid: string) => D().tasks.filter((t) => t.project === pid && !t.archived);
export const allTasks = () => D().tasks.filter((t) => !t.archived && canSee(proj(t.project)));
export const isOver = (t: Task) => Boolean(t.due) && t.status !== "done" && diffD(parse(t.due)!, TODAY) < 0;
export const commentsOf = (tid: string) => D().comments.filter((c) => c.task === tid);
export function progressOf(pid: string) {
  const ts = tasksOf(pid);
  if (!ts.length) return 0;
  return Math.round((ts.filter((t) => t.status === "done").length / ts.length) * 100);
}

/** Anyone who acts: a member, an agent (auto, research…), or Kai, the coding agent (agent:coding-agent). */
export function who(id: string | null | undefined): { id: string; name: string; c: string; agent: boolean } | null {
  if (!id) return null;
  const m = mem(id);
  if (m) return { id, name: m.name, c: m.c, agent: false };
  const a = (D().agents ?? []).find((x) => x.handle === id) ?? AGENTS.find((x) => x.handle === id);
  if (a) return { id, name: a.name, c: a.c, agent: true };
  const tool = CODING_TOOLS.find((x) => x.id === id);
  if (tool) return { id, name: tool.name, c: tool.c, agent: true };
  return null;
}

/** Who a coding session's engine codes as ("opencode" → "Kai"). */
export const toolName = (tool: string) => who(`agent:${tool}`)?.name ?? tool;

/* ---------- activity ---------- */
export function logAct(verb: string, t?: Task | null, extra = "") {
  D().activity.unshift({ id: uid("a"), by: D().me, verb, task: t?.id ?? null, project: t?.project ?? null, at: Date.now(), extra });
  if (t) t.updated = Date.now();
}
