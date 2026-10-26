// The API behind the store. Signed in, /w/{slug} of one of your workspaces loads it from the API
// into the same shapes the screens read (src/data/types.ts), so screens don't change; the demo
// workspace (/w/dotrix, seeded) stays in this browser. Writes go to the API as they happen:
// the store changes first (the screen answers at once), then the request; a refused request
// puts the item back as the API has it and says why.
//
// Reads: the directory (you, workspaces, members, projects, agents) loads here; everything else
// (issues, notifications, activity, threads, coding, documents, knowledge, automations, audit)
// arrives through the StoreBridge's TanStack queries, which replace the store's slots.
// Writes: the store changes first (the screen answers at once), then the request; a refused
// request puts the item back as the API has it and says why. Wired: the workspace, members and
// roles, projects (create, edit, status, star), issues (create, every field, checklists, repeats,
// stars, attachments, comments), notifications (read state), agents (the list), Knowledge (save),
// files (upload, rename, duplicate, delete), automations (on/off, add a preset).
// Settings and Members (your account, the workspace, its people, agents' settings) are in
// account.ts. Not yet: chat and coding (their own step).
import { api, apiFetch, authPost, hasSession, problemMessage, unwrap, type Schemas } from "@/lib/api";
import { issueKeys, issueOptions, type Issue, type Scope } from "@/lib/issues";
import { RECUR_OUT, STATUS_OUT, fromApi, hashTint, logComment, ms, toAttachment, toAutomation, toChecklist, toFile, toTask } from "@/lib/view-models";
import { invalidateLiveQueries, queryClient } from "@/lib/queryClient";

import { fmtDate, uid } from "../core/utils";
import { fileType } from "../ui/helpers";
import { toast } from "../ui/toast";
import { htmlToMd } from "./markdown";
import { D, S, mutate, render, setLiveData } from "./store";
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
  /** Bumped when a send fails after the store showed the change: the bridge re-mirrors the queries'
   *  (still pre-edit) data over the optimistic edit — an unchanged refetch keeps its array identity,
   *  so the bridge wouldn't rewrite the slot on its own. */
  mirrorRev: 0,
};
export const isLive = () => live.mode === "live";

/** API writes also refresh the TanStack caches the migrated screens read (store writes go
 *  through mutate() + these senders; hook-read screens refetch on invalidation). */
const send = <T>(p: Promise<{ data?: T; error?: unknown; response: Response }>) =>
  unwrap(p).then((r) => {
    invalidateLiveQueries();
    return r;
  });

type WIssue = Schemas["WorkspaceIssue"];
/** Every workspace-scoped issues cache (the filtered list variants and the starred-keys set share this prefix). */
const issuesCaches = { queryKey: ["issues", "workspace"] } as const;
/** Optimistically edit a task's issue rows in the caches, so hook-read screens update with the store's copy;
 * the send's invalidation refetches the truth (and a failed send's invalidate puts it back). */
const patchIssueRows = (t: Task, patch: (r: WIssue) => Partial<WIssue>) => {
  queryClient.setQueriesData<WIssue[]>(issuesCaches, (rows) => rows?.map((r) => (r.key === t.key && r.project_id === t.project ? { ...r, ...patch(r) } : r)));
};
/** An id the API made (a project or user), not one the store made up for a new item. */

/** A send failed after the store already showed the change: put the queries' data back over it. */
const restoreMirror = () => {
  live.mirrorRev++;
  render();
};

/** Refetch the workspace's agents (Settings' agent edits) — the bridge mirrors them in. */
export async function reloadAgents() {
  if (!isLive()) return;
  await queryClient.invalidateQueries({ queryKey: ["agents", live.ws!.id] });
}

/* ---------- loading ---------- */

export async function myWorkspaces(): Promise<W[]> {
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
    const [me, wss] = await Promise.all([unwrap(api.GET("/v1/me")), myWorkspaces()]);
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

/** An issue changed in the store (applyPatch): send what the API has. */
export function taskPatched(t: Task, keys: (keyof Task)[]) {
  if (!isLive() || t.key.startsWith("new-")) return;
  const body = issueFields(t, keys);
  if (!Object.keys(body).length) return;
  const { archived, parent, ...rest } = body;
  patchIssueRows(t, () => ({
    ...(rest as Partial<WIssue>),
    ...(archived === undefined ? {} : { archived_at: archived ? new Date().toISOString() : null }),
    ...(parent === undefined ? {} : { parent_key: parent }),
  }));
  void send(
    api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(t.project), key: t.key } }, body }),
  )
    .then(async (i) => {
      t.updated = ms(i.updated_at);
      // A repeating issue just finished: the API made the next one.
      if (i.repeated_as && !D().tasks.some((x) => x.key === i.repeated_as)) {
        const next = await unwrap(
          api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(t.project), key: i.repeated_as } } }),
        );
        const nt = toTask(next, t.project, next.rank);
        D().tasks.push(nt);
        render();
        toast(`Next “${nt.title}” scheduled for ${nt.due ? fmtDate(nt.due) : "later"}`, { kind: "info" });
      }
    })
    .catch((e) => {
      failed(`“${t.title}”`, e);
      invalidateLiveQueries();
      restoreMirror(); // undo the edit the store already showed
    });
}

/** A new issue in the store (createTask): create it, then take the key the API gives it. */
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
  const made = send(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues", { params: { path: projectPath(t.project) }, body }))
    .then((i) => {
      const was = t.id;
      t.id = t.key = i.key;
      if (S.ui.drawer === was) S.ui.drawer = i.key;
      D().activity.forEach((a) => a.task === was && (a.task = i.key));
      render();
      // Starred while it was being created.
      if (t.fav) taskStarred(t);
    })
    .catch((e) => {
      failed(`“${t.title}”`, e);
      D().tasks = D().tasks.filter((x) => x !== t);
      render();
    });
  creating.set(t, made);
  return made;
}
const creating = new WeakMap<Task, Promise<void>>();
/** Settles once a new issue is on the API (or failed to be), e.g. before adding files to it. */
export const whenCreated = (t: Task) => creating.get(t) ?? Promise.resolve();

const issueScope = (pid: string): Scope => ({ workspaceId: wsId(), projectId: pid });

/** The task's issue detail, straight from the query cache — the drawer's useIssue fetches it and
 *  openTask prefetches it, so helpers can read comments/description/attachments synchronously. */
const cachedIssue = (t: Task) => queryClient.getQueryData<Issue>(issueKeys.issue(issueScope(t.project), t.key));

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

export function commentPosted(t: Task, text: string, mentions: string[] = []) {
  if (!isLive() || t.key.startsWith("new-")) return;
  // Show it before the refetch lands: the detail cache feeds liveCommentsOf, the row's count the badge.
  queryClient.setQueryData<Issue>(issueKeys.issue(issueScope(t.project), t.key), (i) =>
    i
      ? {
          ...i,
          log: [
            ...(i.log ?? []),
            {
              id: `pending-${uid("c")}`,
              kind: "commented",
              author_user_id: D().me,
              author_agent: null,
              body: text,
              changes: {},
              created_at: new Date().toISOString(),
            } as Schemas["IssueEventRead"],
          ],
        }
      : i,
  );
  patchIssueRows(t, (r) => ({ comment_count: r.comment_count + 1 }));
  void send(
    api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments", {
      params: { path: { ...projectPath(t.project), key: t.key } },
      body: { body: text, mentions },
    }),
  ).catch((e) => {
    failed("Your comment", e);
    void invalidateLiveQueries();
  });
}

/** A rank change in a list or on the board: place it before the issue that now follows it. */
export function taskRanked(t: Task, before: Task | undefined, after: Task | undefined) {
  if (!isLive() || (!before && !after)) return;
  const body = before ? { before: before.key } : { after: after!.key };
  void send(
    api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/rank", {
      params: { path: { ...projectPath(t.project), key: t.key } },
      body: body as Schemas["RankRequest"],
    }),
  ).catch((e) => {
    failed("The new order", e);
    restoreMirror();
  });
}

const PSTATUS_OUT: Record<Project["status"], Pick<Schemas["ProjectUpdate"], "status" | "health">> = {
  planning: { status: "planning" },
  active: { status: "active", health: "on_track" },
  risk: { status: "active", health: "at_risk" },
  hold: { status: "on_hold" },
  complete: { status: "completed" },
};

/** A project's fields changed in the store: send them. Settles once the API has them (or refused). */
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
  return send(api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}", { params: { path: projectPath(p.id) }, body })).then(
    () => undefined,
    (e) => {
      failed(p.name, e);
      invalidateLiveQueries();
      restoreMirror();
    },
  );
}

export function projectCreated(p: Project) {
  if (!isLive()) return;
  const was = p.id;
  void send(
    api.POST("/v1/workspaces/{workspace_id}/projects", {
      params: { path: { workspace_id: wsId() } },
      body: {
        key: p.key,
        name: p.name,
        source: "docs_only",
        description: p.desc === "No description yet." ? "" : p.desc,
        icon: p.icon,
        color: p.color as Schemas["ProjectColor"],
        access: p.private ? "restricted" : "workspace",
      },
    }),
  )
    .then(async (made) => {
      // Its starter issues were made against the store's id; create them now it exists.
      const starters = D().tasks.filter((t) => t.project === was);
      p.id = made.id;
      p.key = made.key;
      D().projOrder = D().projOrder.map((x) => (x === was ? made.id : x));
      starters.forEach((t) => (t.project = made.id));
      render();
      for (const t of starters) await taskCreated(t); // one at a time, so keys follow their order
      if (p.status !== "planning" || p.due) projectChanged(p, ["status", "due"]);
      render();
    })
    .catch((e) => {
      failed(p.name, e);
      invalidateLiveQueries();
      restoreMirror();
    });
}

export function projectStarred(p: Project) {
  if (!isLive()) return;
  const params = { params: { path: projectPath(p.id) } };
  void send(
    p.fav
      ? api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/star", params)
      : api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/star", params),
  ).catch((e) => {
    failed("The star", e);
    restoreMirror();
  });
}

export function roleChanged(m: Member) {
  if (!isLive()) return;
  void send(
    api.PATCH("/v1/workspaces/{workspace_id}/members/{user_id}", {
      params: { path: { workspace_id: wsId(), user_id: m.id } },
      body: { role: m.role.toLowerCase() as Schemas["Role"] },
    }),
  ).catch((e) => {
    failed(`${m.name}'s role`, e);
    invalidateLiveQueries();
    restoreMirror();
  });
}

export function notifsRead(ids: string[] | "all") {
  if (!isLive() || (ids !== "all" && !ids.length)) return;
  void send(
    api.POST("/v1/workspaces/{workspace_id}/notifications/read", {
      params: { path: { workspace_id: wsId() } },
      body: ids === "all" ? { all: true, ids: [] } : { ids, all: false },
    }),
  ).catch(() => restoreMirror());
}

/* ---------- knowledge, files, automations ---------- */

/** A knowledge file saved from Knowledge: the text shows at once; the API's version replaces the guess. */
export function knowledgeSaved(f: KnowledgeFile, content: string, message: string) {
  if (!isLive()) return;
  const base = f.version;
  f.content = content;
  void send(
    api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/knowledge/files/{path}", {
      params: { path: { ...projectPath(f.project), path: f.path } },
      body: { content, base_version: base, message: message || null },
    }),
  )
    .then((r) => {
      f.version = r.version;
      f.by = D().me;
      f.at = ms(r.updated_at);
      render();
      toast(`Saved ${f.path} (v${r.version})`);
    })
    .catch((e) => {
      failed(f.path, e);
      invalidateLiveQueries();
      restoreMirror();
    });
}

/** An automation switched on or off, or let act without approval, in Settings (the store already shows it). */
export function automationToggled(a: Automation, field: "enabled" | "unattended" = "enabled") {
  if (!isLive()) return;
  void send(
    api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/automations/{automation_id}", {
      params: { path: { ...projectPath(a.project), automation_id: a.id } },
      body: { [field]: !!a[field] },
    }),
  ).catch((e) => {
    failed(a.name, e);
    invalidateLiveQueries();
    restoreMirror();
  });
}

/** The presets in Settings → Automations, as the API takes them. */
export const PRESETS: Record<string, { agent: string; events?: Schemas["AutomationEvent"][]; weekly?: boolean; instructions: string }> = {
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
  void send(
    api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/automations/{automation_id}", {
      params: { path: { ...projectPath(a.project), automation_id: a.id } },
    }),
  ).catch((e) => {
    failed(a.name, e);
    invalidateLiveQueries();
    restoreMirror();
  });
}
/** A preset added in Settings: created for the project, then shown. */
export async function automationAdded(pid: string, preset: string) {
  const spec = PRESETS[preset];
  if (!spec || !isLive()) return;
  try {
    const made = await send(
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
    );
    D().automations.push(toAutomation(made));
    render();
    toast(`Added “${preset}”`);
  } catch (e) {
    failed(`“${preset}”`, e);
  }
}

/** A file uploaded to a project's files; the store shows it once the API has it (converted in the background). */
export async function documentUploaded(file: File, pid: string, onProgress: (pct: number) => void): Promise<void> {
  const doc = await upload<Schemas["DocumentRead"]>(`/v1/workspaces/${wsId()}/projects/${pid}/documents`, file, onProgress);
  D().files.unshift(toFile(doc, pid));
  invalidateLiveQueries();
  render();
  onProgress(100);
}

const docPath = (f: FileItem) => ({ params: { path: { ...projectPath(f.project), document_id: f.id } } });
/** A project file renamed in Files (the store shows the new name already). */
export function fileRenamed(f: FileItem, was: string) {
  if (!isLive()) return;
  void send(api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/documents/{document_id}", { ...docPath(f), body: { filename: f.name } }))
    .then((d) => {
      f.name = d.filename; // as the API cleaned it
      f.type = fileType(d.filename);
      render();
    })
    .catch((e) => {
      failed(`“${was}”`, e);
      f.name = was;
      f.type = fileType(was);
      render();
    });
}

/** A copy of a project file: the API stores and converts it, then it's listed. */
export async function fileDuplicated(f: FileItem) {
  try {
    const d = await send(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/documents/{document_id}/duplicate", docPath(f)));
    const i = D().files.indexOf(f);
    D().files.splice(i + 1, 0, toFile(d, f.project));
    render();
    toast(`Duplicated as ${d.filename}`);
  } catch (e) {
    failed(`The copy of “${f.name}”`, e);
  }
}

/** A project file deleted in Files (already gone from the store): its markdown in Knowledge goes too. */
export function fileDeleted(f: FileItem) {
  if (!isLive()) return;
  // send() already invalidates, so the knowledge mirror picks up the markdown going too.
  void send(api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/documents/{document_id}", docPath(f))).catch((e) => {
    failed(`Deleting “${f.name}”`, e);
    invalidateLiveQueries();
    restoreMirror();
  });
}

/** A file added to an issue (the drawer, or the new-issue form once the issue exists). */
export async function issueFileAttached(file: File, t: Task, onProgress: (pct: number) => void = () => {}): Promise<void> {
  await whenCreated(t);
  if (t.key.startsWith("new-")) throw new Error("The issue wasn't created");
  const i = await upload<Schemas["IssueRead"]>(
    `/v1/workspaces/${wsId()}/projects/${t.project}/issues/${encodeURIComponent(t.key)}/attachments`,
    file,
    onProgress,
  );
  t.attachments = (i.attachments ?? []).map(toAttachment);
  patchIssueRows(t, (r) => ({ attachment_count: r.attachment_count + 1 }));
  invalidateLiveQueries();
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

/* ---------- delete, move ---------- */

/** An issue's star toggled in the store: star or unstar it on the API. */
export function taskStarred(t: Task) {
  if (!isLive() || t.key.startsWith("new-")) return;
  const path = { params: { path: { ...projectPath(t.project), key: t.key } } };
  const on = t.fav;
  // The starred-keys set feeds Task.fav; patch it so every screen's star flips at once.
  queryClient.setQueriesData<WIssue[]>({ queryKey: ["issues", "workspace", wsId(), "starred-keys"] }, (rows) => {
    if (!on) return rows?.filter((r) => !(r.key === t.key && r.project_id === t.project));
    if (!rows || rows.some((r) => r.key === t.key && r.project_id === t.project)) return rows;
    const row = queryClient
      .getQueriesData<WIssue[]>({ queryKey: ["issues", "workspace", wsId()] })
      .flatMap(([, rs]) => rs ?? [])
      .find((r) => r.key === t.key && r.project_id === t.project);
    return row ? [...rows, row] : rows;
  });
  void send(
    on
      ? api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/star", path)
      : api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/star", path),
  ).catch((e) => {
    failed("The star", e);
    mutate(() => (t.fav = !on));
    void invalidateLiveQueries();
  });
}

/** A file detached from an issue (already gone from the store). */
export function attachmentRemoved(t: Task, attachmentId: string) {
  if (!isLive() || t.key.startsWith("new-") || attachmentId.startsWith("counted-")) return;
  patchIssueRows(t, (r) => ({ attachment_count: Math.max(0, r.attachment_count - 1) }));
  void send(
    api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/attachments/{attachment_id}", {
      params: { path: { ...projectPath(t.project), key: t.key, attachment_id: attachmentId } },
    }),
  ).catch((e) => {
    failed("Removing the file", e);
    invalidateLiveQueries();
    restoreMirror();
  });
}

/* ---------- delete, move, comments ---------- */

/* ---------- delete, move, comments ---------- */

/** Issues deleted in the screens (already gone from the store). A delete can't be undone. */
export function tasksDeleted(ts: Task[]) {
  if (!isLive()) return;
  for (const t of ts) {
    if (t.key.startsWith("new-")) continue;
    queryClient.setQueriesData<WIssue[]>(issuesCaches, (rows) => rows?.filter((r) => !(r.key === t.key && r.project_id === t.project)));
    queryClient.removeQueries({ queryKey: issueKeys.issue(issueScope(t.project), t.key) });
    void send(
      api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(t.project), key: t.key } } }),
    ).catch(async (e) => {
      failed(`Deleting “${t.title}”`, e);
      try {
        // Put it back as the API has it.
        const i = await unwrap(
          api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(t.project), key: t.key } } }),
        );
        const back = { ...toTask(i, t.project, t.order), fav: t.fav };
        D().tasks.push(back);
        render();
      } catch {
        /* gone after all */
      }
    });
  }
}

/** A project deleted in the screens (already gone from the store), with everything in it. */
export function projectDeleted(pr: Project) {
  if (!isLive()) return;
  void send(api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}", { params: { path: projectPath(pr.id) } })).catch((e) => {
    failed(`Deleting ${pr.name}`, e);
    invalidateLiveQueries();
    restoreMirror();
  });
}

/** Move an issue to another project: the API creates it there (next key, its history with it) and
 * deletes it here; the store's task becomes the new one. */
export async function taskMoved(t: Task, toProject: string) {
  const from = t.key;
  try {
    const i = await send(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/move", {
        params: { path: { ...projectPath(t.project), key: from } },
        body: { project_id: toProject },
      }),
    );
    Object.assign(t, toTask(i, toProject, t.order), { fav: t.fav });
    if (S.ui.drawer === from) S.ui.drawer = t.id;
    D().comments.forEach((c) => c.task === from && (c.task = t.id));
    D().activity.forEach((a) => a.task === from && (a.task = t.id));
    render();
    toast(`Moved to ${t.key}`);
  } catch (e) {
    failed(`Moving “${t.title}”`, e);
  }
}

const commentPath = (c: Comment) => {
  const t = D().tasks.find((x) => x.id === c.task)!;
  return { ...projectPath(t.project), key: t.key, comment_id: c.id };
};
/** A comment's new text (its author only; the store shows it already). */
export function commentEdited(c: Comment) {
  if (!isLive() || !fromApi(c.id)) return;
  void send(
    api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments/{comment_id}", {
      params: { path: commentPath(c) },
      body: { body: c.text },
    }),
  ).catch((e) => {
    failed("Your comment", e);
    void invalidateLiveQueries();
  });
}
/** A comment deleted (already gone from the store). */
export function commentDeleted(c: Comment) {
  if (!isLive() || !fromApi(c.id)) return;
  void send(api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments/{comment_id}", { params: { path: commentPath(c) } })).catch(
    (e) => {
      failed("Deleting the comment", e);
      void invalidateLiveQueries();
    },
  );
}
/** Your reaction added or taken back (the store shows it already). */
export function commentReacted(c: Comment, emoji: string, on: boolean) {
  if (!isLive() || !fromApi(c.id)) return;
  const path = { params: { path: { ...commentPath(c), emoji } } };
  void send(
    on
      ? api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments/{comment_id}/reactions/{emoji}", path)
      : api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments/{comment_id}/reactions/{emoji}", path),
  ).catch((e) => {
    failed("Your reaction", e);
    void invalidateLiveQueries();
  });
}

const PROJECT_ICONS = new Set([
  "globe",
  "smartphone",
  "megaphone",
  "rocket",
  "component",
  "building-2",
  "layout-grid",
  "palette",
  "code",
  "briefcase",
  "target",
  "layers",
  "zap",
  "heart",
  "folder",
  "sparkles",
]);

/** Create an organisation with its first project (and the template's starter issues), invite
 * people, and return its slug to open. Signed in only; the demo keeps the seeded flow. */
export async function organisationCreated(f: { name: string; project: string; icon: string; tasks: string[]; invites: string[] }): Promise<string> {
  const ws = await send(api.POST("/v1/workspaces", { body: { name: f.name, kind: "organization" } }));
  const inWs = { params: { path: { workspace_id: ws.id } } };
  const letters = f.project.toUpperCase().replace(/[^A-Z ]/g, "");
  let key = letters
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w[0])
    .join("")
    .slice(0, 4);
  if (key.length < 2) key = (letters.replace(/\s/g, "") + "PRJ").slice(0, 3);
  const project = await send(
    api.POST("/v1/workspaces/{workspace_id}/projects", {
      ...inWs,
      body: { key, name: f.project, description: "", source: "docs_only", access: "workspace", icon: PROJECT_ICONS.has(f.icon) ? f.icon : "folder" },
    }),
  );
  const inProject = { params: { path: { workspace_id: ws.id, project_id: project.id } } };
  for (const title of f.tasks)
    // one at a time, so keys follow the template's order
    await send(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues", {
        ...inProject,
        body: {
          title,
          type: "task",
          description: "",
          status: "todo",
          priority: "none",
          depends_on: [],
          labels: [],
          components: [],
          links: [],
          checklist: [],
          parent: null,
        },
      }),
    );
  for (const email of f.invites)
    await send(api.POST("/v1/workspaces/{workspace_id}/invites", { ...inWs, body: { email, role: "member" } })).catch((e) =>
      failed(`The invite to ${email}`, e),
    );
  return ws.slug;
}
