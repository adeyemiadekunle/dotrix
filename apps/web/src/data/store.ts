// Store for React: live workspaces read from TanStack Query slots (data/live.ts), while
// UI preferences, view filters, and ephemeral overlay state live here. Demo seed data is
// isolated in ../demo/runtime and loaded only on /demo or /w/dotrix.
import { useSyncExternalStore } from "react";

import type { CodingSession as LiveCodingSession } from "@/lib/coding";
import { PCOLORS } from "../core/constants";
import { AGENTS, CODING_TOOLS } from "../core/team";
import { TODAY, diffD, iso, parse, uid } from "../core/utils";
import type { CodingSession, Data, Filter, Project, Task } from "./types";

const PREFS_KEY = "dotrix.prefs.v1";
const LEGACY_STORE_KEY = "dotrix.studio.v2";

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
  name: "",
  title: "",
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

export interface DemoHooks {
  saveData: (data: Data) => void;
  reset: () => void;
  openRequest: (q: { thread?: string; task?: string }) => void;
  codingSessions: (data: Data) => LiveCodingSession[];
  decideChange: (changeId: string, approve: boolean, reason?: string) => void;
  alwaysAllow: (changeId: string) => void;
  answerCheckpoint: (changeId: string, answer: "continue" | "steer" | "stop", note?: string) => void;
  startCoding: (t: { id: string; key: string; title: string; project: string }, tool: CodingSession["tool"], note?: string) => string | null;
  decideCoding: (cs: CodingSession, approve: boolean, reason?: string) => void;
  continueLimited: (at: { thread?: string; notif?: string }, whenReset: boolean, markNotifRead: () => void) => void;
}

let demoHooks: DemoHooks | null = null;
export function registerDemoHooks(hooks: DemoHooks) {
  demoHooks = hooks;
}
export const demoRuntime = () => demoHooks;

export function emptyData(): Data {
  return {
    ws: { id: "", name: "dotrix", plan: "Personal", url: "", c: "#1D1C1A" },
    workspaces: [],
    me: "",
    members: [],
    projects: [],
    tasks: [],
    comments: [],
    activity: [],
    notifs: [],
    files: [],
    projOrder: [],
    savedViews: [],
    recentSearches: [],
    sessions: [],
    notifPrefs: {},
    agents: [],
    threads: [],
    knowledge: [],
    coding: [],
    audit: [],
    automations: [],
  };
}

interface SavedPrefs {
  prefs?: Partial<Prefs>;
  views?: Record<string, View>;
  collapsed?: boolean;
}

function loadPrefs(): SavedPrefs | null {
  try {
    const raw = localStorage.getItem(PREFS_KEY) ?? localStorage.getItem(LEGACY_STORE_KEY);
    if (raw) {
      const j = JSON.parse(raw) as SavedPrefs;
      if (j && typeof j === "object") {
        // Never hydrate demo user identity ("Tanjim Islam") into live preferences.
        const prefs = { ...(j.prefs ?? {}) };
        if (prefs.name === "Tanjim Islam") delete prefs.name;
        if (prefs.title === "Head of Product") delete prefs.title;
        return { prefs, views: j.views, collapsed: j.collapsed };
      }
    }
  } catch {
    /* storage blocked or corrupt */
  }
  return null;
}
const saved = loadPrefs();

export const S = {
  data: emptyData(),
  prefs: { ...DEFAULT_PREFS, ...(saved?.prefs ?? {}) } as Prefs,
  views: saved?.views ?? ({} as Record<string, View>),
  ui: {
    collapsed: Boolean(saved?.collapsed),
    mnav: false,
    expanded: {} as Record<string, boolean>,
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
    chatBusy: null as string | null,
    chatQ: "",
    codingQ: "",
    showArchivedSessions: false,
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
    agentsSheet: false,
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

/** A live workspace's data, mirrored in from the TanStack queries by the StoreBridge — null outside live workspaces. */
let liveData: Data | null = null;
export function setLiveData(d: Data | null) {
  liveData = d;
}
function writeNow() {
  clearTimeout(saveTimer);
  saveTimer = undefined;
  try {
    const persistedPrefs = liveData ? S.prefs : { ...S.prefs, name: "", title: "" };
    localStorage.setItem(PREFS_KEY, JSON.stringify({ prefs: persistedPrefs, views: S.views, collapsed: S.ui.collapsed }));
  } catch {
    /* storage full or blocked: keep working in memory */
  }
  if (!liveData && demoHooks) demoHooks.saveData(S.data);
}
export function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(writeNow, 150);
}
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
  const a = (D().agents ?? []).find((x) => x.handle === id) ?? (!liveData ? AGENTS.find((x) => x.handle === id) : undefined);
  if (a) return { id, name: a.name, c: a.c, agent: true };
  const tool = CODING_TOOLS.find((x) => x.id === id);
  if (tool) return { id, name: tool.name, c: tool.c, agent: true };
  return null;
}

/** Who a coding session's engine codes as ("opencode" → "Kai"). */
export const toolName = (tool: string) => who(`agent:${tool}`)?.name ?? tool;

/* ---------- activity ---------- */
export function logAct(verb: string, t?: Task | null, extra = "") {
  if (liveData) return;
  D().activity.unshift({ id: uid("a"), by: D().me, verb, task: t?.id ?? null, project: t?.project ?? null, at: Date.now(), extra });
  if (t) t.updated = Date.now();
}
