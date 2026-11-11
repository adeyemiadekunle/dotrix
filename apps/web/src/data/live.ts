// The API behind the store. Signed in, /w/{slug} of one of your workspaces loads it from the API
// into the same shapes the screens read (src/data/types.ts), so screens don't change; the demo
// workspace (/w/dotrix, seeded) stays in this browser.
//
// Reads: the store's lists (tasks, members, projects, agents, notifications, activity, files, …) are
// the TanStack query cache, read as it is (lib/store-slots.ts); StoreBridge keeps those queries loaded.
// Writes: each one is a TanStack mutation (`write` below). It shows the change in the query cache at
// once, so every screen and the store answer together; sends it; and refetches what it touches. A
// refused request puts the cache back as it was and says why. Wired: the workspace, members and
// roles, projects (create, edit, status, star, delete), issues (create, every field, checklists,
// repeats, stars, rank, move, delete, attachments, comments and reactions), notifications (read
// state), Knowledge (save), files (upload, rename, duplicate, delete), automations (on/off, add,
// remove). Settings and Members (your account, the workspace, its people, agents' settings) are in
// account.ts. Chat and Codes read and write through their own queries (lib/agent.ts, lib/coding.ts).
import { api, apiFetch, authPost, hasSession, problemMessage, unwrap, type Schemas } from "@/lib/api";
import { issueKeys, issueOptions, type Issue, type Scope } from "@/lib/issues";
import { RECUR_OUT, STATUS_OUT, fromApi, hashTint, logComment, ms, toAttachment, toAutomation, toChecklist, toFile, toTask } from "@/lib/view-models";
import { invalidateLiveQueries, queryClient } from "@/lib/queryClient";
import { MutationObserver, type QueryKey } from "@tanstack/react-query";
import { SLOT_NAMES, forgetSlots, readSlot } from "@/lib/store-slots";

import { featuresQuery } from "../core/features";
import { fmtDate, uid } from "../core/utils";
import { fileType } from "../ui/helpers";
import { toast } from "../ui/toast";
import { htmlToMd } from "./markdown";
import { D, S, render, setLiveData } from "./store";
import type { Automation, Comment, Data, FileItem, KnowledgeFile, Member, Project, Task } from "./types";

type W = Schemas["WorkspaceWithRole"];

/** Run after a real workspace loads (account.ts adds its pending invites). */
export const onLoaded: (() => void)[] = [];

/** Where the store's data comes from right now. */
export const live = {
  mode: "demo" as "demo" | "loading" | "live" | "error",
  slug: null as string | null,
  ws: null as W | null,
  error: "",
  /** The bridge set it once the directory queries (members, agents, projects) have landed — the shell waits on it. */
  dirReady: false,
};
export const isLive = () => live.mode === "live";

/* ---------- writes: the cache first, then the API ---------- */

/** What a change can show up in, by the first part of a query's key: refetched once the API has answered. */
const ISSUES = ["issues", "activity", "notifications", "graph", "search", "audit", "project-readiness", "coding-sessions", "coding", "agent-activity"];
const PROJECTS = ["projects", "issues", "activity", "audit", "notifications", "search", "project-readiness"];
const MEMBERS = ["members", "projects", "audit"];
const NOTIFICATIONS = ["notifications"];
const KNOWLEDGE = ["knowledge", "graph", "search", "activity", "audit", "project-readiness", "repo-knowledge"];
const DOCUMENTS = ["documents", ...KNOWLEDGE];
const AUTOMATIONS = ["automations", "audit"];
const refresh = (kinds: readonly string[]) => void queryClient.invalidateQueries({ predicate: (q) => kinds.includes(q.queryKey[0] as string) });

type Req<T> = Promise<{ data?: T; error?: unknown; response: Response }>;
interface Write<T> {
  /** What a refusal names ("“Fix the login” didn't save: …"); empty says nothing. */
  what: string;
  /** The caches it changes (by key prefix): kept as they were, to put back if the API refuses it. */
  touches: QueryKey[];
  /** The change, made in those caches at once; every screen and the store's lists read them. */
  show?: () => void;
  request: () => Req<T>;
  /** The kinds of query to refetch once it has settled (see ISSUES and the rest). */
  refresh: readonly string[];
  /** The API's answer, put where the screens read it. */
  done?: (r: T) => void | Promise<void>;
  /** After a refusal, once the caches are back as they were. */
  undone?: () => void;
}

/** A change, as a TanStack mutation: shown in the query cache at once (refetches of what it touches are
 * cancelled, so a stale answer can't land over it), sent, then refetched from what the API has. A refusal
 * puts the caches back as they were and says why. Resolves with the API's answer, or undefined if refused. */
function write<T>(w: Write<T>): Promise<T | undefined> {
  let before: [QueryKey, unknown][] = [];
  const m = new MutationObserver<T, unknown, void>(queryClient, {
    mutationKey: ["write", ...w.refresh.slice(0, 1)],
    onMutate: async () => {
      await Promise.all(w.touches.map((k) => queryClient.cancelQueries({ queryKey: k })));
      before = w.touches.flatMap((k) => queryClient.getQueriesData({ queryKey: k }));
      w.show?.();
      render();
    },
    mutationFn: () => unwrap(w.request()),
    onSuccess: (r) => w.done?.(r),
    onError: (e) => {
      for (const [k, d] of before) queryClient.setQueryData(k, d);
      // A change the store made in place that never reached a cache goes too.
      forgetSlots();
      if (w.what) failed(w.what, e);
      w.undone?.();
      render();
    },
    onSettled: () => refresh(w.refresh),
  });
  return m.mutate().catch(() => undefined);
}

type WIssue = Schemas["WorkspaceIssue"];
type Row = { key: string; project_id: string };
/** Every workspace-scoped issues cache (the filtered list variants and the starred-keys set share this prefix). */
const issuesCaches = { queryKey: ["issues", "workspace"] } as const;
const isRow = (t: Pick<Task, "key" | "project">) => (r: Row) => r.key === t.key && r.project_id === t.project;
/** Change a task's rows in every issue list. */
const patchIssueRows = (t: Task, patch: (r: WIssue) => Partial<WIssue>) => {
  const it = isRow(t);
  queryClient.setQueriesData<WIssue[]>(issuesCaches, (rows) => rows?.map((r) => (it(r) ? { ...r, ...patch(r) } : r)));
};
/** The issue lists a new issue belongs in before the API has answered: not the starred or archived ones,
 * and a list of someone's issues only when it is theirs. */
const listsNewIssue = (key: readonly unknown[], row: WIssue) => {
  const f = key[3];
  if (key[2] !== live.ws?.id || !f || typeof f !== "object") return false;
  const { starred, archived, assignee, reporter, watching, status, type, label, due_before } = f as Record<string, unknown>;
  if (starred || watching || reporter || label || due_before || archived === "only") return false;
  if (assignee && !(assignee === "me" && row.assignee_user_id === D().me)) return false;
  if (Array.isArray(status) && !status.includes(row.status)) return false;
  return !(Array.isArray(type) && !type.includes(row.type));
};
/** Put a row for an issue being created into the lists it belongs in, so the board shows it at once. */
const addIssueRow = (row: WIssue) => {
  queryClient.setQueriesData<WIssue[]>({ ...issuesCaches, predicate: (q) => listsNewIssue(q.queryKey, row) }, (rows) => (rows ? [...rows, row] : rows));
};
/** Take a task's rows out of every issue list. */
const dropIssueRows = (t: Pick<Task, "key" | "project">) => {
  const it = isRow(t);
  queryClient.setQueriesData<WIssue[]>(issuesCaches, (rows) => rows?.filter((r) => !it(r)));
};
/** Change a cached list (one query), if it has loaded. */
const patchList = <R>(key: QueryKey, fn: (rows: R[]) => R[]) => queryClient.setQueryData<R[]>(key, (rows) => rows && fn(rows));
/** Whether a list query has loaded: before it has, the store keeps its own list and a change goes there. */
const loaded = (key: QueryKey) => queryClient.getQueryData(key) !== undefined;

/** Refetch the workspace's agents (Settings' agent edits): the store reads that query. */
export async function reloadAgents() {
  if (!isLive()) return;
  await queryClient.invalidateQueries({ queryKey: ["agents", live.ws!.id] });
}

/* ---------- loading ---------- */

async function myWorkspaces(): Promise<W[]> {
  return unwrap(api.GET("/v1/workspaces"));
}

/** Load workspace {slug} from the API into the store. False when it isn't one of yours. */
export async function loadWorkspace(slug: string): Promise<boolean> {
  if (!hasSession()) return false;
  live.mode = "loading";
  live.slug = slug;
  // A retry after an error — or a hop between workspaces — refetches the queries the
  // bridge mirrors; a query that settled in error only fetches again on invalidation.
  void invalidateLiveQueries();
  render();
  try {
    // The features first, so menus know whether organisations exist here (core/features.ts). An
    // API without the probe (older than the web) just offers none, rather than failing to load.
    const [me, wss] = await Promise.all([unwrap(api.GET("/v1/me")), myWorkspaces(), queryClient.fetchQuery(featuresQuery).catch(() => undefined)]);
    const ws = wss.find((w) => w.slug === slug);
    if (!ws) {
      live.mode = "live"; // so showDemo puts the demo's data back
      showDemo();
      return false;
    }
    // Everything workspace-scoped — members, projects, agents, issues, notifications,
    // activity, conversations, coding, documents, knowledge, automations, the audit log —
    // comes from the StoreBridge's TanStack queries; the store holds you and your
    // workspaces here, and the bridge fills the rest as its queries land.
    live.dirReady = false;
    const data: Data = {
      ws: { id: ws.id, name: ws.name, c: hashTint(ws.id), plan: ws.kind === "personal" ? "Personal" : "Team", kind: ws.kind, url: ws.slug },
      workspaces: wss.map((w) => ({
        id: w.id,
        name: w.name,
        c: hashTint(w.id),
        plan: w.kind === "personal" ? "Personal" : "Organisation",
        kind: w.kind,
        slug: w.slug,
      })),
      me: me.id,
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
    // Its lists are the query cache's, read as they are now (lib/store-slots.ts): nothing copies them in,
    // so a lookup never lags behind a write. Until a list's queries have loaded, it's an array of its own;
    // after that a change goes through its save (below), and replacing the list does nothing.
    for (const name of SLOT_NAMES) {
      let early: unknown[] = [];
      Object.defineProperty(data, name, {
        enumerable: true,
        get: () => readSlot(name, ws.id) ?? early,
        set: (v: unknown[]) => {
          if (readSlot(name, ws.id) === undefined) early = v;
          else if (import.meta.env.DEV) console.warn(`D().${name} is the query cache here: change it through its save in data/live.ts.`);
        },
      });
    }
    // Live data gets its own object — the demo's seed stays in S.data, untouched.
    setLiveData(data);
    S.prefs.name = me.display_name;
    S.prefs.title = me.title ?? "";
    live.ws = ws;
    live.mode = "live";
    // Nothing opened against the previous data stays open.
    Object.assign(S.ui, { drawer: null, modals: [], pop: null, palette: null, sel: new Set<string>(), composer: null, editCell: null });
    render();
    onLoaded.forEach((f) => f());
    try {
      localStorage.setItem("dotrix.lastWorkspace", slug);
    } catch {
      /* only a convenience */
    }
    return true;
  } catch (e) {
    setLiveData(null);
    live.mode = "error";
    live.error = e instanceof Error ? e.message : "The workspace didn't load.";
    render();
    return true;
  }
}

/** Back to the demo workspace's data (its own address, or signing out). */
export function showDemo() {
  if (live.mode === "demo") return;
  setLiveData(null);
  live.mode = "demo";
  live.slug = null;
  live.ws = null;
  Object.assign(S.ui, { drawer: null, modals: [], pop: null, palette: null, sel: new Set<string>(), composer: null, editCell: null });
  render();
}

/** Where "/" goes: your last workspace, or your first; the demo without a session. */
export async function homeSlug(): Promise<string | null> {
  if (!hasSession()) return null;
  try {
    const wss = await myWorkspaces();
    let last: string | null = null;
    try {
      last = localStorage.getItem("dotrix.lastWorkspace");
    } catch {
      /* ignore */
    }
    return (wss.find((w) => w.slug === last) ?? wss.find((w) => w.kind === "organization") ?? wss[0])?.slug ?? null;
  } catch {
    return null;
  }
}

export async function signOutLive() {
  await authPost("logout").catch(() => undefined);
  location.assign("/login");
}

/* ---------- writing ---------- */

const wsId = () => live.ws!.id;
const projectPath = (pid: string) => ({ workspace_id: wsId(), project_id: pid });

function failed(what: string, e: unknown) {
  const msg = e instanceof Error ? e.message : "";
  toast(`${what} didn't save${msg ? `: ${msg}` : ""}`, { kind: "err", ms: 6000 });
}

/** The fields of a patch the API has, as IssueUpdate. */
function issueFields(t: Task, keys: (keyof Task)[]): Schemas["IssueUpdate"] {
  const body: Schemas["IssueUpdate"] = {};
  for (const k of keys) {
    if (k === "status") body.status = STATUS_OUT[t.status];
    else if (k === "priority") body.priority = t.priority as Schemas["Priority"];
    else if (k === "title") body.title = t.title;
    else if (k === "desc") body.description = htmlToMd(t.desc);
    else if (k === "due") body.due = t.due;
    else if (k === "start") body.scheduled = t.start;
    else if (k === "labels") body.labels = t.labels;
    else if (k === "deps") body.depends_on = t.deps;
    else if (k === "type") body.type = t.type;
    else if (k === "parent") body.parent = t.parent ?? null;
    else if (k === "subtasks") body.checklist = toChecklist(t.subtasks);
    else if (k === "archived") body.archived = Boolean(t.archived);
    else if (k === "recur") body.recurrence = t.recur ? (RECUR_OUT[t.recur] ?? null) : null;
    else if (k === "estimate") {
      const n = Number.parseFloat(t.estimate ?? "");
      body.estimate = Number.isFinite(n) ? n : null;
    } else if (k === "assignee") {
      const a = t.assignee;
      if (a?.startsWith("agent:")) {
        body.assignee_agent = a.slice(6) as Schemas["AgentAssignee"];
        body.assignee_user_id = null;
      } else {
        body.assignee_user_id = a;
        body.assignee_agent = null;
      }
    }
  }
  return body;
}

/** An issue changed in the store (applyPatch): show it in the issue's rows and detail, then send it. */
export function taskPatched(t: Task, keys: (keyof Task)[]) {
  if (!isLive()) return;
  const body = issueFields(t, keys);
  if (!Object.keys(body).length) return;
  const { archived, parent, ...rest } = body;
  const fields = {
    ...(rest as Partial<WIssue>),
    ...(archived === undefined ? {} : { archived_at: archived ? new Date().toISOString() : null }),
    ...(parent === undefined ? {} : { parent_key: parent }),
  };
  const send = (at: Pick<Task, "key" | "project">) => {
    const rows = { ...at, title: t.title } as Task;
    return write({
      what: `“${t.title}”`,
      touches: [["issues"]],
      show: () => {
        patchIssueRows(rows, () => fields);
        queryClient.setQueryData<Issue>(detailKey(at), (i) => i && ({ ...i, ...fields } as Issue));
      },
      request: () =>
        api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(at.project), key: at.key } }, body }),
      refresh: ISSUES,
      done: async (i) => {
        // A repeating issue just finished: the API made the next one (the refetch lists it).
        if (!i.repeated_as || D().tasks.some((x) => x.key === i.repeated_as)) return;
        const next = await unwrap(
          api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(at.project), key: i.repeated_as } } }),
        ).catch(() => undefined);
        if (next) toast(`Next “${next.title}” scheduled for ${next.due ? fmtDate(next.due) : "later"}`, { kind: "info" });
      },
    });
  };
  if (isProvisional(t)) {
    // Shown on the provisional row now; sent under the real key once the issue exists.
    patchIssueRows(t, () => fields);
    render();
  }
  onceCreated(t, send);
}

/** A new issue in the store (createTask): shown in the lists under a provisional key, created, then given the API's key. */
export function taskCreated(t: Task): Promise<void> {
  // A new project's starter issues wait for the project (projectCreated sends them).
  if (!isLive() || !fromApi(t.project)) return Promise.resolve();
  const local = t.id;
  t.key = t.id = `new-${uid("")}`;
  if (S.ui.drawer === local) S.ui.drawer = t.id;
  const full = issueFields(t, ["status", "priority", "assignee", "due", "start", "labels", "deps", "type", "estimate", "desc", "subtasks", "recur"]);
  const { components: _c, links: _l, ...rest } = full;
  const body: Schemas["IssueCreate"] = {
    ...rest,
    title: t.title,
    type: t.type,
    description: full.description ?? "",
    depends_on: full.depends_on ?? [],
    labels: full.labels ?? [],
    checklist: full.checklist ?? [],
    status: full.status ?? "todo",
    priority: full.priority ?? "none",
    parent: t.parent ?? null,
  };
  const was = t.id;
  const p = D().projects.find((x) => x.id === t.project);
  const now = new Date().toISOString();
  const row = {
    ...rest,
    key: was,
    title: t.title,
    type: t.type,
    status: body.status,
    priority: body.priority,
    labels: body.labels,
    depends_on: body.depends_on,
    checklist: body.checklist,
    parent_key: t.parent ?? null,
    archived_at: null,
    attachment_count: 0,
    comment_count: 0,
    rank: t.order,
    created_at: now,
    updated_at: now,
    project_id: t.project,
    project_key: p?.key ?? "",
    project_name: p?.name ?? "",
  } as unknown as WIssue;
  // The store's Task for it is made again from the cache whenever the lists change: look it up by key.
  const copies = () => new Set([t, ...D().tasks.filter((x) => x.project === t.project && x.key === was)]);
  const made = write({
    what: `“${t.title}”`,
    touches: [["issues", "workspace"]],
    show: () => addIssueRow(row),
    request: () => api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues", { params: { path: projectPath(t.project) }, body }),
    refresh: ISSUES,
    done: (i) => {
      const { description: _d, ...answer } = i;
      const it = isRow({ key: was, project: t.project });
      queryClient.setQueriesData<WIssue[]>(issuesCaches, (rows) => rows?.map((r) => (it(r) ? ({ ...r, ...answer } as WIssue) : r)));
      realKeys.set(was, i.key);
      setTimeout(() => realKeys.delete(was), 60_000);
      for (const x of copies()) x.id = x.key = i.key;
      if (S.ui.drawer === was) S.ui.drawer = i.key;
      D().activity.forEach((a) => a.task === was && (a.task = i.key));
      render();
    },
    undone: () => {
      const gone = copies();
      D().tasks = D().tasks.filter((x) => !gone.has(x));
      if (S.ui.drawer === was) S.ui.drawer = null;
    },
  })
    .then(() => undefined)
    .finally(() => creating.delete(was));
  creating.set(was, made);
  return made;
}
/** Issues being created, by their provisional key (the store's Task object changes as the lists do). */
const creating = new Map<string, Promise<void>>();
/** Settles once a new issue is on the API (or failed to be), e.g. before adding files to it. */
const whenCreated = (t: Task) => creating.get(t.key) ?? Promise.resolve();
/** The API's key for each issue made here, by its provisional key (dropped a minute after the create). */
const realKeys = new Map<string, string>();
/** The last change queued for each issue still being created, so changes to it are sent in the order they were made. */
const chains = new Map<string, Promise<void>>();
const isProvisional = (t: Pick<Task, "key">) => t.key.startsWith("new-");
/** The API's key for a key that may be provisional (undefined if the create failed). */
const realKey = (k: string) => (k.startsWith("new-") ? realKeys.get(k) : k);

/** Run `send` once the task exists on the API, with the task as it is then (looked up again by its real key).
 *  Changes to the same task are sent one after the other, in order. A failed create drops them. */
function onceCreated(t: Task, send: (real: Task) => Promise<unknown> | void): void {
  if (!isProvisional(t)) {
    void send(t);
    return;
  }
  const provisional = t.key;
  const gate = chains.get(provisional) ?? whenCreated(t);
  const next = gate.then(async () => {
    const key = realKeys.get(provisional);
    if (!key) return;
    const real = D().tasks.find((x) => x.key === key && x.project === t.project) ?? { ...t, key, id: key };
    try {
      await send(real);
    } catch {
      /* write reports its own refusals */
    }
  });
  chains.set(provisional, next);
  void next.then(() => chains.get(provisional) === next && chains.delete(provisional));
}

const issueScope = (pid: string): Scope => ({ workspaceId: wsId(), projectId: pid });
const detailKey = (t: Pick<Task, "key" | "project">) => issueKeys.issue(issueScope(t.project), t.key);

/** The task's issue detail, straight from the query cache — the drawer's useIssue fetches it and
 *  openTask prefetches it, so helpers can read comments/description/attachments synchronously. */
const cachedIssue = (t: Task) => queryClient.getQueryData<Issue>(detailKey(t));

/** Fetch the issue detail so cachedIssue has it (what loadComments did, through the query cache). */
export function prefetchIssue(t: Task) {
  if (!isLive() || t.key.startsWith("new-")) return;
  void queryClient.ensureQueryData(issueOptions(issueScope(t.project), t.key));
}

/** A task's comments from the cached issue detail — the live-mode replacement for D().comments. */
export function liveCommentsOf(t: Task): Comment[] {
  if (!isLive() || t.key.startsWith("new-")) return [];
  return (cachedIssue(t)?.log ?? []).filter((e) => e.kind === "commented" && e.body).map((e) => logComment(e, t.id));
}

/** A comment by id, searched across every cached issue detail (PopLayer's reaction picker). */
export function liveCommentById(id: string): Comment | undefined {
  if (!isLive()) return undefined;
  for (const [key, issue] of queryClient.getQueriesData<Issue>({ queryKey: ["issues"] })) {
    const e = (issue?.log ?? []).find((x) => x.id === id && x.kind === "commented" && x.body);
    if (e) {
      const t = D().tasks.find((x) => x.project === key[1] && x.key === key[3]);
      return t ? logComment(e, t.id) : undefined;
    }
  }
}

type Event = Schemas["IssueEventRead"];
/** Change an issue's history (its comments) in the cached detail. */
const patchLog = (t: Pick<Task, "key" | "project">, fn: (log: Event[]) => Event[]) =>
  queryClient.setQueryData<Issue>(detailKey(t), (i) => i && { ...i, log: fn(i.log ?? []) });

export function commentPosted(t: Task, text: string, mentions: string[] = []) {
  if (!isLive()) return;
  if (isProvisional(t)) {
    patchIssueRows(t, (r) => ({ comment_count: r.comment_count + 1 }));
    render();
  }
  onceCreated(t, (real) => sendComment(real, text, mentions));
}
function sendComment(t: Task, text: string, mentions: string[]) {
  const at = { key: t.key, project: t.project };
  return write({
    what: "Your comment",
    touches: [["issues"]],
    show: () => {
      const e = {
        id: `pending-${uid("c")}`,
        kind: "commented",
        author_user_id: D().me,
        author_agent: null,
        body: text,
        changes: {},
        created_at: new Date().toISOString(),
      };
      patchLog(at, (log) => [...log, e as Event]);
      patchIssueRows(t, (r) => ({ comment_count: r.comment_count + 1 }));
    },
    request: () =>
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments", {
        params: { path: { ...projectPath(at.project), key: at.key } },
        body: { body: text, mentions },
      }),
    refresh: ISSUES,
  });
}

/** A rank change in a list or on the board: place it before the issue that now follows it. */
export function taskRanked(t: Task, before: Task | undefined, after: Task | undefined, rank = t.order) {
  if (!isLive() || (!before && !after)) return;
  // Neighbours may still be being created too: remember their keys now, and wait for them.
  const near = before ? { side: "before" as const, task: before, key: before.key } : { side: "after" as const, task: after!, key: after!.key };
  if (isProvisional(t)) {
    patchIssueRows(t, () => ({ rank }));
    render();
  }
  onceCreated(t, async (real) => {
    await whenCreated(near.task);
    const neighbour = realKey(near.key);
    if (!neighbour) return;
    const body = near.side === "before" ? { before: neighbour } : { after: neighbour };
    const at = { key: real.key, project: real.project };
    await write({
      what: "The new order",
      touches: [["issues", "workspace"]],
      // A project's lists sort by rank: show the new place now; the refetch brings the API's own number.
      show: () => patchIssueRows(real, () => ({ rank })),
      request: () =>
        api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/rank", {
          params: { path: { ...projectPath(at.project), key: at.key } },
          body: body as Schemas["RankRequest"],
        }),
      refresh: ISSUES,
    });
  });
}

const PSTATUS_OUT: Record<Project["status"], Pick<Schemas["ProjectUpdate"], "status" | "health">> = {
  planning: { status: "planning" },
  active: { status: "active", health: "on_track" },
  risk: { status: "active", health: "at_risk" },
  hold: { status: "on_hold" },
  complete: { status: "completed" },
};

type ProjectRow = Schemas["ProjectRead"];
const projectsKey = () => ["projects", wsId()] as const;
const patchProject = (id: string, fields: Partial<ProjectRow>) =>
  patchList<ProjectRow>(projectsKey(), (ps) => ps.map((x) => (x.id === id ? { ...x, ...fields } : x)));

/** A project's fields changed in the store: show them in the projects list, then send them. Settles once the API has them (or refused). */
export function projectChanged(p: Project, keys: (keyof Project)[]): Promise<void> {
  if (!isLive()) return Promise.resolve();
  const body: Schemas["ProjectUpdate"] = {};
  for (const k of keys) {
    if (k === "name") body.name = p.name;
    else if (k === "desc") body.description = p.desc;
    else if (k === "icon") body.icon = p.icon;
    else if (k === "color") body.color = p.color as Schemas["ProjectColor"];
    else if (k === "due") body.target_date = p.due || null;
    else if (k === "status") Object.assign(body, PSTATUS_OUT[p.status]);
    else if (k === "private") body.access = p.private ? "restricted" : "workspace";
    else if (k === "archived") body.archived = Boolean(p.archived);
  }
  if (!Object.keys(body).length) return Promise.resolve();
  const { archived, ...same } = body;
  const fields = { ...same, ...(archived === undefined ? {} : { archived_at: archived ? new Date().toISOString() : null }) } as Partial<ProjectRow>;
  return write({
    what: p.name,
    touches: [projectsKey()],
    show: () => patchProject(p.id, fields),
    request: () => api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}", { params: { path: projectPath(p.id) }, body }),
    refresh: PROJECTS,
  }).then(() => undefined);
}

/** A project made in the store (newProject): listed under its provisional id, created, then given the API's id and its starter issues. */
export function projectCreated(p: Project) {
  if (!isLive()) return;
  const was = p.id;
  const now = new Date().toISOString();
  const body: Schemas["ProjectCreate"] = {
    key: p.key,
    name: p.name,
    source: "docs_only",
    description: p.desc === "No description yet." ? "" : p.desc,
    icon: p.icon,
    color: p.color as Schemas["ProjectColor"],
    access: p.private ? "restricted" : "workspace",
  };
  const row = {
    ...body,
    id: was,
    workspace_id: wsId(),
    repo_url: null,
    model: null,
    specialist_model: null,
    automatic_model_routing: false,
    health: null,
    target_date: p.due || null,
    status: "planning",
    archived_at: null,
    knowledge_revision: 0,
    created_at: now,
    updated_at: now,
  } as unknown as ProjectRow;
  void write({
    what: p.name,
    touches: [projectsKey()],
    show: () => patchList<ProjectRow>(projectsKey(), (ps) => [...ps, row]),
    request: () => api.POST("/v1/workspaces/{workspace_id}/projects", { params: { path: { workspace_id: wsId() } }, body }),
    refresh: PROJECTS,
    done: async (made) => {
      patchList<ProjectRow>(projectsKey(), (ps) => ps.map((x) => (x.id === was ? made : x)));
      // Its starter issues were made against the store's id; create them now it exists.
      const starters = D().tasks.filter((t) => t.project === was);
      p.id = made.id;
      p.key = made.key;
      D().projOrder = D().projOrder.map((x) => (x === was ? made.id : x));
      starters.forEach((t) => (t.project = made.id));
      render();
      for (const t of starters) await taskCreated(t); // one at a time, so keys follow their order
      if (p.status !== "planning" || p.due) void projectChanged(p, ["status", "due"]);
      render();
    },
    undone: () => {
      D().projOrder = D().projOrder.filter((x) => x !== was);
    },
  });
}

export function projectStarred(p: Project) {
  if (!isLive()) return;
  const params = { params: { path: projectPath(p.id) } };
  const on = p.fav;
  const key = [...projectsKey(), "starred"];
  void write({
    what: "The star",
    touches: [key],
    show: () => patchList<string>(key, (ids) => (on ? [...ids.filter((x) => x !== p.id), p.id] : ids.filter((x) => x !== p.id))),
    request: () =>
      on
        ? api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/star", params)
        : api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/star", params),
    refresh: ["projects"],
  });
}

export function roleChanged(m: Member) {
  if (!isLive()) return;
  const role = m.role.toLowerCase() as Schemas["Role"];
  void write({
    what: `${m.name}'s role`,
    touches: [["members", wsId()]],
    // The members list and the copy the projects read; the invites list has no user_id to match.
    show: () =>
      queryClient.setQueriesData<Schemas["MemberRead"][]>({ queryKey: ["members", wsId()] }, (rows) =>
        rows?.map((r) => (r.user_id === m.id ? { ...r, role } : r)),
      ),
    request: () => api.PATCH("/v1/workspaces/{workspace_id}/members/{user_id}", { params: { path: { workspace_id: wsId(), user_id: m.id } }, body: { role } }),
    refresh: MEMBERS,
  });
}

/** Notifications marked read (the API keeps read, not unread). */
export function notifsRead(ids: string[] | "all") {
  if (!isLive() || (ids !== "all" && !ids.length)) return;
  const has = (id: string) => ids === "all" || ids.includes(id);
  void write({
    what: "",
    touches: [["notifications", wsId()]],
    show: () =>
      queryClient.setQueriesData<Schemas["NotificationRead"][]>({ queryKey: ["notifications", wsId()] }, (rows) =>
        Array.isArray(rows) ? rows.map((n) => (has(n.id) ? { ...n, read: true } : n)) : rows,
      ),
    request: () =>
      api.POST("/v1/workspaces/{workspace_id}/notifications/read", {
        params: { path: { workspace_id: wsId() } },
        body: ids === "all" ? { all: true, ids: [] } : { ids, all: false },
      }),
    refresh: NOTIFICATIONS,
  });
}

/* ---------- knowledge, files, automations ---------- */

/** A knowledge file saved from Knowledge: the text shows at once; the API's version replaces the guess. */
export function knowledgeSaved(f: KnowledgeFile, content: string, message: string) {
  if (!isLive()) return;
  const base = f.version;
  const fileKey = ["knowledge", f.project, "file", f.path];
  f.content = content;
  void write({
    what: f.path,
    touches: [["knowledge", f.project]],
    show: () => queryClient.setQueryData<Schemas["FileRead"]>(fileKey, (x) => x && { ...x, content }),
    request: () =>
      api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/knowledge/files/{path}", {
        params: { path: { ...projectPath(f.project), path: f.path } },
        body: { content, base_version: base, message: message || null },
      }),
    refresh: KNOWLEDGE,
    done: (r) => {
      queryClient.setQueryData<Schemas["FileRead"]>(fileKey, (x) => x && { ...x, content, version: r.version, updated_at: r.updated_at });
      queryClient.setQueryData<Schemas["Manifest"]>(
        ["knowledge", f.project],
        (m) => m && { ...m, files: m.files.map((x) => (x.path === f.path ? { ...x, version: r.version, updated_at: r.updated_at } : x)) },
      );
      f.version = r.version;
      f.by = D().me;
      f.at = ms(r.updated_at);
      render();
      toast(`Saved ${f.path} (v${r.version})`);
    },
  });
}

type AutomationRow = Schemas["AutomationRead"];
const automationsKey = (pid: string) => ["automations", pid] as const;

/** An automation switched on or off, or let act without approval, in Settings (the store already shows it). */
export function automationToggled(a: Automation, field: "enabled" | "unattended" = "enabled") {
  if (!isLive()) return;
  const on = !!a[field];
  void write({
    what: a.name,
    touches: [automationsKey(a.project)],
    show: () => patchList<AutomationRow>(automationsKey(a.project), (as) => as.map((x) => (x.id === a.id ? { ...x, [field]: on } : x))),
    request: () =>
      api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/automations/{automation_id}", {
        params: { path: { ...projectPath(a.project), automation_id: a.id } },
        body: { [field]: on },
      }),
    refresh: AUTOMATIONS,
  });
}

/** The presets in Settings → Automations, as the API takes them. */
const PRESETS: Record<string, { agent: string; events?: Schemas["AutomationEvent"][]; weekly?: boolean; instructions: string }> = {
  "Keep documents current": {
    agent: "documentation",
    events: ["changes.approved", "issue.done"],
    instructions: "After approved changes or a finished issue, propose the matching current-state and roadmap updates, as changes to approve.",
  },
  "Flag stale documents": { agent: "documentation", weekly: true, instructions: "List the documents that may be out of date, and why." },
  "Triage new bugs": {
    agent: "auto",
    events: ["issue.created"],
    instructions: "For each new issue, check for duplicates and fill in missing fields, as changes to approve.",
  },
  "Watch a topic": {
    agent: "research",
    weekly: true,
    instructions: "Re-check the topic against the newest research note and report what changed, with sources.",
  },
};

/** A preset toggled off: the automation is deleted (the list row has no remove of its own). */
export function automationRemoved(a: Automation) {
  if (!isLive()) return;
  void write({
    what: a.name,
    touches: [automationsKey(a.project)],
    show: () => patchList<AutomationRow>(automationsKey(a.project), (as) => as.filter((x) => x.id !== a.id)),
    request: () =>
      api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/automations/{automation_id}", {
        params: { path: { ...projectPath(a.project), automation_id: a.id } },
      }),
    refresh: AUTOMATIONS,
  });
}
/** A preset added in Settings: created for the project, then shown. */
export async function automationAdded(pid: string, preset: string) {
  const spec = PRESETS[preset];
  if (!spec || !isLive()) return;
  const made = await write({
    what: `“${preset}”`,
    touches: [],
    request: () =>
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/automations", {
        params: { path: projectPath(pid) },
        body: {
          name: preset,
          agent: spec.agent,
          instructions: spec.instructions,
          events: spec.events ?? [],
          schedule_hour: spec.weekly ? 8 : null,
          schedule_weekday: spec.weekly ? 0 : null,
          enabled: true,
          max_runs_per_day: null,
          unattended: false,
        },
      }),
    refresh: AUTOMATIONS,
    done: (a) => {
      if (loaded(automationsKey(pid))) patchList<AutomationRow>(automationsKey(pid), (as) => [...as, a]);
      else D().automations.push(toAutomation(a));
    },
  });
  if (made) toast(`Added “${preset}”`);
}

type DocumentRow = Schemas["DocumentRead"];
const documentsKey = (pid: string) => ["documents", pid] as const;

/** A file uploaded to a project's files; listed once the API has it (converted in the background). */
export async function documentUploaded(file: File, pid: string, onProgress: (pct: number) => void): Promise<void> {
  const doc = await upload<DocumentRow>(`/v1/workspaces/${wsId()}/projects/${pid}/documents`, file, onProgress);
  if (loaded(documentsKey(pid))) patchList<DocumentRow>(documentsKey(pid), (ds) => [doc, ...ds]);
  else D().files.unshift(toFile(doc, pid));
  refresh(DOCUMENTS);
  render();
  onProgress(100);
}

const docPath = (f: FileItem) => ({ params: { path: { ...projectPath(f.project), document_id: f.id } } });
const patchDocument = (f: FileItem, fields: Partial<DocumentRow>) =>
  patchList<DocumentRow>(documentsKey(f.project), (ds) => ds.map((d) => (d.id === f.id ? { ...d, ...fields } : d)));

/** A project file renamed in Files (the store shows the new name already). */
export function fileRenamed(f: FileItem, was: string) {
  if (!isLive()) return;
  const name = f.name;
  void write({
    what: `“${was}”`,
    touches: [documentsKey(f.project)],
    show: () => patchDocument(f, { filename: name }),
    request: () => api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/documents/{document_id}", { ...docPath(f), body: { filename: name } }),
    refresh: DOCUMENTS,
    // As the API cleaned it.
    done: (d) => {
      patchDocument(f, d);
      f.name = d.filename;
      f.type = fileType(d.filename);
    },
    undone: () => {
      f.name = was;
      f.type = fileType(was);
    },
  });
}

/** A copy of a project file: the API stores and converts it, then it's listed after the original. */
export async function fileDuplicated(f: FileItem) {
  const d = await write({
    what: `The copy of “${f.name}”`,
    touches: [],
    request: () => api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/documents/{document_id}/duplicate", docPath(f)),
    refresh: DOCUMENTS,
    done: (d) => {
      if (loaded(documentsKey(f.project)))
        patchList<DocumentRow>(documentsKey(f.project), (ds) => {
          const i = ds.findIndex((x) => x.id === f.id);
          return [...ds.slice(0, i + 1), d, ...ds.slice(i + 1)];
        });
      else D().files.splice(D().files.indexOf(f) + 1, 0, toFile(d, f.project));
    },
  });
  if (d) toast(`Duplicated as ${d.filename}`);
}

/** A project file deleted in Files (already gone from the store): its markdown in Knowledge goes too. */
export function fileDeleted(f: FileItem) {
  if (!isLive()) return;
  void write({
    what: `Deleting “${f.name}”`,
    touches: [documentsKey(f.project)],
    show: () => patchList<DocumentRow>(documentsKey(f.project), (ds) => ds.filter((d) => d.id !== f.id)),
    request: () => api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/documents/{document_id}", docPath(f)),
    refresh: DOCUMENTS,
  });
}

/** A file added to an issue (the drawer, or the new-issue form once the issue exists). */
export async function issueFileAttached(file: File, t: Task, onProgress: (pct: number) => void = () => {}): Promise<void> {
  await whenCreated(t);
  // The task may have been made again from the cache with its new key meanwhile: the key is on `t` either way.
  if (t.key.startsWith("new-")) throw new Error("The issue wasn't created");
  const i = await upload<Schemas["IssueRead"]>(
    `/v1/workspaces/${wsId()}/projects/${t.project}/issues/${encodeURIComponent(t.key)}/attachments`,
    file,
    onProgress,
  );
  queryClient.setQueryData<Issue>(detailKey(t), (d) => (d ? { ...d, attachments: i.attachments } : d));
  patchIssueRows(t, (r) => ({ attachment_count: (i.attachments ?? []).length || r.attachment_count + 1 }));
  t.attachments = (i.attachments ?? []).map(toAttachment);
  refresh(ISSUES);
  render();
  onProgress(100);
}
/** Files picked in the new-issue form, added once the issue is on the API. */
export function filesAttached(t: Task, files: File[]) {
  for (const file of files) void issueFileAttached(file, t).catch((e) => failed(file.name, e));
}

async function upload<T>(url: string, file: File, onProgress: (pct: number) => void): Promise<T> {
  const body = new FormData();
  body.append("file", file);
  onProgress(15);
  const res = await apiFetch(url, { method: "POST", body });
  if (!res.ok) {
    const problem = (await res.json().catch(() => undefined)) as Parameters<typeof problemMessage>[0];
    throw new Error(problemMessage(problem) ?? "The file didn't upload");
  }
  return (await res.json()) as T;
}

/* ---------- stars, attachments ---------- */

/** An issue's star toggled in the store: shown in the starred set every screen's star reads, then sent. */
export function taskStarred(t: Task) {
  if (!isLive()) return;
  const on = t.fav;
  const key = ["issues", "workspace", wsId(), "starred-keys"];
  const shown = (at: Pick<Task, "key" | "project">) => {
    const it = isRow(at);
    queryClient.setQueryData<WIssue[]>(key, (rows) => {
      if (!on) return rows?.filter((r) => !it(r));
      if (!rows || rows.some(it)) return rows;
      const row = queryClient
        .getQueriesData<WIssue[]>({ queryKey: ["issues", "workspace", wsId()] })
        .flatMap(([, rs]) => (Array.isArray(rs) ? rs : []))
        .find(it);
      return row ? [...rows, row] : rows;
    });
  };
  if (isProvisional(t)) {
    shown(t);
    render();
  }
  onceCreated(t, (real) => {
    const path = { params: { path: { ...projectPath(real.project), key: real.key } } };
    return write({
      what: "The star",
      touches: [key],
      show: () => shown(real),
      request: () =>
        on
          ? api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/star", path)
          : api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/star", path),
      refresh: ISSUES,
    });
  });
}

/** A file detached from an issue (already gone from the store). */
export function attachmentRemoved(t: Task, attachmentId: string) {
  if (!isLive() || t.key.startsWith("new-") || attachmentId.startsWith("counted-")) return;
  const at = { key: t.key, project: t.project };
  void write({
    what: "Removing the file",
    touches: [["issues"]],
    show: () => {
      patchIssueRows(t, (r) => ({ attachment_count: Math.max(0, r.attachment_count - 1) }));
      queryClient.setQueryData<Issue>(detailKey(at), (i) => i && { ...i, attachments: (i.attachments ?? []).filter((a) => a.id !== attachmentId) });
    },
    request: () =>
      api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/attachments/{attachment_id}", {
        params: { path: { ...projectPath(at.project), key: at.key, attachment_id: attachmentId } },
      }),
    refresh: ISSUES,
  });
}

/* ---------- delete, move, comments ---------- */

/** Issues deleted in the screens: gone from the lists at once, back if the API refuses. A delete can't be undone. */
export function tasksDeleted(ts: Task[]) {
  if (!isLive()) return;
  for (const t of ts) {
    if (isProvisional(t)) {
      dropIssueRows(t);
      render();
    }
    onceCreated(t, (real) => {
      const at = { key: real.key, project: real.project };
      return write({
        what: `Deleting “${t.title}”`,
        touches: [["issues", "workspace"]],
        show: () => dropIssueRows(at),
        request: () =>
          api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(at.project), key: at.key } } }),
        refresh: ISSUES,
        done: () => queryClient.removeQueries({ queryKey: detailKey(at) }),
      });
    });
  }
}

/** A project deleted in the screens, with everything in it: gone from the lists at once, back if the API refuses. */
export function projectDeleted(pr: Project) {
  if (!isLive()) return;
  void write({
    what: `Deleting ${pr.name}`,
    touches: [projectsKey(), ["issues", "workspace"]],
    show: () => {
      patchList<ProjectRow>(projectsKey(), (ps) => ps.filter((x) => x.id !== pr.id));
      queryClient.setQueriesData<WIssue[]>(issuesCaches, (rows) => rows?.filter((r) => r.project_id !== pr.id));
    },
    request: () => api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}", { params: { path: projectPath(pr.id) } }),
    refresh: PROJECTS,
  });
}

/** Move an issue to another project: the API creates it there (next key, its history with it) and
 * deletes it here; its rows become the new issue's. */
export async function taskMoved(t: Task, toProject: string) {
  const from = { key: t.key, project: t.project };
  const to = D().projects.find((p) => p.id === toProject);
  const i = await write({
    what: `Moving “${t.title}”`,
    touches: [],
    request: () =>
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/move", {
        params: { path: { ...projectPath(from.project), key: from.key } },
        body: { project_id: toProject },
      }),
    refresh: ISSUES,
    done: (i) => {
      const { description: _d, ...answer } = i;
      const it = isRow(from);
      queryClient.setQueriesData<WIssue[]>(issuesCaches, (rows) =>
        rows?.map((r) => (it(r) ? ({ ...r, ...answer, project_id: toProject, project_key: to?.key ?? "", project_name: to?.name ?? "" } as WIssue) : r)),
      );
      queryClient.removeQueries({ queryKey: detailKey(from) });
      Object.assign(t, toTask(i, toProject, t.order), { fav: t.fav });
      if (S.ui.drawer === from.key) S.ui.drawer = i.key;
      D().comments.forEach((c) => c.task === from.key && (c.task = i.key));
      D().activity.forEach((a) => a.task === from.key && (a.task = i.key));
    },
  });
  if (i) toast(`Moved to ${i.key}`);
}

/** The issue a comment is on, as the cache knows it now. */
const commentIssue = (c: Comment) => {
  const t = D().tasks.find((x) => x.id === c.task)!;
  return { key: t.key, project: t.project, t };
};
const commentPath = (c: Comment) => {
  const at = commentIssue(c);
  return { ...projectPath(at.project), key: at.key, comment_id: c.id };
};
/** A comment's new text (its author only; the store shows it already). */
export function commentEdited(c: Comment) {
  if (!isLive() || !fromApi(c.id)) return;
  const at = commentIssue(c);
  const text = c.text;
  void write({
    what: "Your comment",
    touches: [detailKey(at)],
    show: () => patchLog(at, (log) => log.map((e) => (e.id === c.id ? { ...e, body: text, edited_at: new Date().toISOString() } : e))),
    request: () =>
      api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments/{comment_id}", {
        params: { path: commentPath(c) },
        body: { body: text },
      }),
    refresh: ISSUES,
  });
}
/** A comment deleted (already gone from the store). */
export function commentDeleted(c: Comment) {
  if (!isLive() || !fromApi(c.id)) return;
  const at = commentIssue(c);
  void write({
    what: "Deleting the comment",
    touches: [["issues"]],
    show: () => {
      patchLog(at, (log) => log.filter((e) => e.id !== c.id));
      patchIssueRows(at.t, (r) => ({ comment_count: Math.max(0, r.comment_count - 1) }));
    },
    request: () => api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments/{comment_id}", { params: { path: commentPath(c) } }),
    refresh: ISSUES,
  });
}
/** Your reaction added or taken back (the store shows it already). */
export function commentReacted(c: Comment, emoji: string, on: boolean) {
  if (!isLive() || !fromApi(c.id)) return;
  const at = commentIssue(c);
  const me = D().me;
  const path = { params: { path: { ...commentPath(c), emoji } } };
  void write({
    what: "Your reaction",
    touches: [detailKey(at)],
    show: () =>
      patchLog(at, (log) =>
        log.map((e) => {
          if (e.id !== c.id) return e;
          const who = (e.reactions?.[emoji] ?? []).filter((x) => x !== me);
          return { ...e, reactions: { ...(e.reactions ?? {}), [emoji]: on ? [...who, me] : who } };
        }),
      ),
    request: () =>
      on
        ? api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments/{comment_id}/reactions/{emoji}", path)
        : api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments/{comment_id}/reactions/{emoji}", path),
    refresh: ISSUES,
  });
}

/* ---------- decisions from the agents panel and the corner notices ---------- */

/** What an approval or a rejection can change: the run and what it was about to write, the queues, the Inbox. */
const DECIDED = [...ISSUES, ...KNOWLEDGE, "approvals", "agent", "threads", "conversations", "run-events", "coding-run", "coding-runs", "coding-session"];
type CodingRun = Schemas["CodingRunRead"];
/** A turn of Kai's waits on you: to start, or (Manual) for its checked changes to be pushed. */
const waitsOnYou = (r: CodingRun) => (r.status === "awaiting_approval" || r.status === "changes_ready") && r.can_decide;
const nothingWaits = () => {
  toast("Nothing here waits on you any more", { kind: "info" });
  refresh(DECIDED);
  return false;
};

async function decideCodingRun(projectId: string, r: CodingRun, approve: boolean): Promise<boolean> {
  const pushing = r.status === "changes_ready";
  const done = await write({
    what: approve ? "The approval" : "The rejection",
    touches: [],
    request: () =>
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/runs/{coding_run_id}/decision", {
        params: { path: { ...projectPath(projectId), coding_run_id: r.id } },
        body: { decision: approve ? "approve" : "reject", reason: null },
      }),
    refresh: DECIDED,
  });
  if (done)
    toast(approve ? (pushing ? `Pushing Kai's changes on ${r.issue_key}` : `Kai is starting on ${r.issue_key}`) : `Rejected Kai's turn on ${r.issue_key}`);
  return done !== undefined;
}

/** Approve or reject a turn of Kai's by its id (an approval notification names it). */
export async function codingRunDecided(projectId: string, runId: string, approve: boolean): Promise<boolean> {
  try {
    const r = await unwrap(
      api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/runs/{coding_run_id}", {
        params: { path: { ...projectPath(projectId), coding_run_id: runId } },
      }),
    );
    return waitsOnYou(r) ? decideCodingRun(projectId, r, approve) : nothingWaits();
  } catch (e) {
    failed(approve ? "The approval" : "The rejection", e);
    return false;
  }
}

/** Approve or reject the turn of a Kai session that waits on you (the session list doesn't name it: its turns do). */
export async function codingSessionDecided(projectId: string, sessionId: string, approve: boolean): Promise<boolean> {
  try {
    const runs = await unwrap(
      api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/sessions/{session_id}", {
        params: { path: { ...projectPath(projectId), session_id: sessionId } },
      }),
    );
    const r = [...runs].reverse().find(waitsOnYou);
    return r ? decideCodingRun(projectId, r, approve) : nothingWaits();
  } catch (e) {
    failed(approve ? "The approval" : "The rejection", e);
    return false;
  }
}

/** Approve or reject every change an agent's run waits on you for. */
export async function runChangesDecided(projectId: string, runId: string, approve: boolean): Promise<boolean> {
  try {
    const approvals = await unwrap(api.GET("/v1/workspaces/{workspace_id}/approvals", { params: { path: { workspace_id: wsId() } } }));
    const pending = approvals.filter((a) => a.run_id === runId && a.status === "pending");
    if (!pending.length) return nothingWaits();
    const decision: "approve" | "reject" = approve ? "approve" : "reject";
    const done = await write({
      what: approve ? "The approval" : "The rejection",
      touches: [],
      request: () =>
        api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs/{run_id}/decisions", {
          params: { path: { ...projectPath(projectId), run_id: runId } },
          body: { decisions: pending.map((a) => ({ approval_id: a.id, decision })) },
        }),
      refresh: DECIDED,
    });
    const n = pending.length === 1 ? "the change" : `${pending.length} changes`;
    if (done) toast(approve ? `Approved ${n}` : `Rejected ${n}`);
    return done !== undefined;
  } catch (e) {
    failed(approve ? "The approval" : "The rejection", e);
    return false;
  }
}
