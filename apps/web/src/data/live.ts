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
import {
  RECUR_OUT,
  STATUS_OUT,
  fromApi,
  hashTint,
  logComment,
  ms,
  toAgent,
  toAttachment,
  toAutomation,
  toChecklist,
  toFile,
  toKnowledge,
  toMember,
  toProject,
  toTask,
} from "@/lib/view-models";
import { invalidateLiveQueries } from "@/lib/queryClient";

import { fmtDate, uid } from "../core/utils";
import { fileType } from "../ui/helpers";
import { toast } from "../ui/toast";
import { htmlToMd, mdToHtml } from "./markdown";
import { D, S, mutate, persist, render } from "./store";
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
  /** The demo workspace's data while a real one is shown, so the demo keeps its edits. */
  demo: null as Data | null,
};
export const isLive = () => live.mode === "live";

/** API writes also refresh the TanStack caches the migrated screens read (store writes go
 *  through mutate() + these senders; hook-read screens refetch on invalidation). */
const send = <T>(p: Promise<{ data?: T; error?: unknown; response: Response }>) =>
  unwrap(p).then((r) => {
    invalidateLiveQueries();
    return r;
  });
// While a real workspace is shown, this browser keeps saving the demo's data, never the API's.
persist.data = () => (live.mode === "demo" ? S.data : (live.demo ?? S.data));
/** An id the API made (a project or user), not one the store made up for a new item. */

/** The agents list again, after one was saved, reset, or created in Settings. */
export async function reloadAgents() {
  if (!isLive()) return;
  try {
    const agents = await unwrap(api.GET("/v1/workspaces/{workspace_id}/agents", { params: { path: { workspace_id: live.ws!.id } } }));
    D().agents = agents.map(toAgent);
    render();
  } catch {
    /* leave what's shown */
  }
}

/* ---------- loading ---------- */

export async function myWorkspaces(): Promise<W[]> {
  return unwrap(api.GET("/v1/workspaces"));
}

/** A project's knowledge files with their content (the manifest lists paths and versions only). */
async function loadKnowledge(wsId: string, pid: string): Promise<KnowledgeFile[]> {
  const path = { workspace_id: wsId, project_id: pid };
  const manifest = await unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/knowledge", { params: { path } }));
  return Promise.all(
    manifest.files
      .filter((f) => !f.deleted)
      .map((f) =>
        unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/knowledge/files/{path}", { params: { path: { ...path, path: f.path } } })).then(
          (r) => toKnowledge(r, pid),
        ),
      ),
  );
}

/** Load workspace {slug} from the API into the store. False when it isn't one of yours. */
export async function loadWorkspace(slug: string): Promise<boolean> {
  if (!hasSession()) return false;
  live.mode = "loading";
  live.slug = slug;
  render();
  try {
    const [me, wss] = await Promise.all([unwrap(api.GET("/v1/me")), myWorkspaces()]);
    const ws = wss.find((w) => w.slug === slug);
    if (!ws) {
      live.mode = "live"; // so showDemo puts the demo's data back
      showDemo();
      return false;
    }
    const path = { params: { path: { workspace_id: ws.id } } };
    // Issues, notifications, activity, conversations, coding sessions, documents, knowledge,
    // automations and the audit log come from the StoreBridge's TanStack queries — the store
    // only holds the directory here (you, workspaces, members, projects, agents).
    const [members, projects, starred, agents] = await Promise.all([
      unwrap(api.GET("/v1/workspaces/{workspace_id}/members", path)),
      unwrap(api.GET("/v1/workspaces/{workspace_id}/projects", path)),
      unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/starred", path)).catch(() => []),
      unwrap(api.GET("/v1/workspaces/{workspace_id}/agents", path)).catch(() => []),
    ]);
    const stars = new Set((starred as { id: string }[]).map((p) => p.id));
    const ps = projects.map((p) => toProject(p, members, stars));
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
      members: members.map(toMember),
      projects: ps,
      tasks: [],
      comments: [],
      activity: [],
      notifs: [],
      files: [],
      projOrder: [...ps.filter((p) => p.fav), ...ps.filter((p) => !p.fav)].map((p) => p.id),
      savedViews: [],
      recentSearches: [],
      sessions: [],
      notifPrefs: {},
      agents: (agents as Schemas["AgentRead"][]).map(toAgent),
      threads: [],
      knowledge: [],
      coding: [],
      audit: [],
      automations: [],
    };
    if (live.demo === null) live.demo = S.data; // set aside the demo's data the first time only
    S.data = data;
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
    live.mode = "error";
    live.error = e instanceof Error ? e.message : "The workspace didn't load.";
    render();
    return true;
  }
}

/** Back to the demo workspace's data (its own address, or signing out). */
export function showDemo() {
  if (live.mode === "demo") return;
  if (live.demo) S.data = live.demo;
  live.demo = null;
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

/** Put an issue back as the API has it (after a refused change). */
async function reloadTask(t: Task) {
  try {
    const i = await unwrap(
      api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(t.project), key: t.key } } }),
    );
    Object.assign(t, toTask(i, t.project, t.order), { fav: t.fav });
    render();
  } catch {
    /* leave it */
  }
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
      void reloadTask(t);
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

/** Comments of an issue, when its drawer opens. */
export async function loadComments(t: Task) {
  if (!isLive() || t.key.startsWith("new-")) return;
  try {
    const i = await unwrap(
      api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(t.project), key: t.key } } }),
    );
    const cs: Comment[] = (i.log ?? []).filter((e) => e.kind === "commented" && e.body).map((e) => logComment(e, t.id));
    D().comments = [...D().comments.filter((c) => c.task !== t.id), ...cs];
    // The full issue has the description and its attachments, which lists leave out.
    if (!t.desc) t.desc = mdToHtml(i.description);
    t.attachments = (i.attachments ?? []).map(toAttachment);
    render();
  } catch {
    /* the drawer still shows what the list had */
  }
}

export function commentPosted(t: Task, text: string, mentions: string[] = []) {
  if (!isLive()) return;
  void send(
    api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments", {
      params: { path: { ...projectPath(t.project), key: t.key } },
      body: { body: text, mentions },
    }),
  )
    .then((i) => {
      // The comment shown since it was posted takes the API's id, so it can be edited or reacted to.
      const posted = [...(i.log ?? [])].reverse().find((e) => e.kind === "commented" && e.body === text);
      const local = D().comments.find((c) => c.task === t.id && c.text === text && !fromApi(c.id));
      if (posted?.id && local) local.id = posted.id;
    })
    .catch((e) => failed("Your comment", e));
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
  ).catch((e) => failed("The new order", e));
}

const PSTATUS_OUT: Record<Project["status"], Pick<Schemas["ProjectUpdate"], "status" | "health">> = {
  planning: { status: "planning" },
  active: { status: "active", health: "on_track" },
  risk: { status: "active", health: "at_risk" },
  hold: { status: "on_hold" },
  complete: { status: "completed" },
};

async function reloadProjects() {
  if (isLive()) await loadWorkspace(live.slug!);
}

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
      void reloadProjects();
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
      void reloadProjects();
    });
}

export function projectStarred(p: Project) {
  if (!isLive()) return;
  const params = { params: { path: projectPath(p.id) } };
  void send(
    p.fav
      ? api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/star", params)
      : api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/star", params),
  ).catch((e) => failed("The star", e));
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
    void reloadProjects();
  });
}

export function notifsRead(ids: string[] | "all") {
  if (!isLive() || (ids !== "all" && !ids.length)) return;
  void send(
    api.POST("/v1/workspaces/{workspace_id}/notifications/read", {
      params: { path: { workspace_id: wsId() } },
      body: ids === "all" ? { all: true, ids: [] } : { ids, all: false },
    }),
  ).catch(() => undefined);
}

/* ---------- knowledge, files, automations ---------- */

async function reloadKnowledge(pid: string) {
  if (!isLive()) return;
  try {
    const files = await loadKnowledge(wsId(), pid);
    D().knowledge = [...D().knowledge.filter((f) => f.project !== pid), ...files];
    render();
  } catch {
    /* leave what's shown */
  }
}

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
      void reloadKnowledge(f.project);
    });
}

async function reloadAutomations(pid: string) {
  if (!isLive()) return;
  try {
    const autos = await unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/automations", { params: { path: projectPath(pid) } }));
    D().automations = [...D().automations.filter((a) => a.project !== pid), ...autos.map(toAutomation)];
    render();
  } catch {
    /* leave what's shown */
  }
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
    void reloadAutomations(a.project);
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
    void reloadAutomations(a.project);
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
async function reloadFiles(pid: string) {
  try {
    const docs = await unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/documents", { params: { path: projectPath(pid) } }));
    D().files = [...D().files.filter((f) => f.project !== pid), ...docs.map((d) => toFile(d, pid))];
    render();
  } catch {
    /* leave what's shown */
  }
}

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
  void send(api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/documents/{document_id}", docPath(f)))
    .then(() => reloadKnowledge(f.project))
    .catch((e) => {
      failed(`Deleting “${f.name}”`, e);
      void reloadFiles(f.project);
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
  void send(
    on
      ? api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/star", path)
      : api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/star", path),
  ).catch((e) => {
    failed("The star", e);
    mutate(() => (t.fav = !on));
  });
}

/** A file detached from an issue (already gone from the store). */
export function attachmentRemoved(t: Task, attachmentId: string) {
  if (!isLive() || t.key.startsWith("new-") || attachmentId.startsWith("counted-")) return;
  void send(
    api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/attachments/{attachment_id}", {
      params: { path: { ...projectPath(t.project), key: t.key, attachment_id: attachmentId } },
    }),
  ).catch((e) => {
    failed("Removing the file", e);
    void reloadTask(t);
  });
}

/* ---------- delete, move, comments ---------- */

/* ---------- delete, move, comments ---------- */

/** Issues deleted in the screens (already gone from the store). A delete can't be undone. */
export function tasksDeleted(ts: Task[]) {
  if (!isLive()) return;
  for (const t of ts) {
    if (t.key.startsWith("new-")) continue;
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
    void reloadProjects();
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
async function reloadComments(c: Comment) {
  const t = D().tasks.find((x) => x.id === c.task);
  if (t) await loadComments(t);
}
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
    void reloadComments(c);
  });
}
/** A comment deleted (already gone from the store). */
export function commentDeleted(c: Comment) {
  if (!isLive() || !fromApi(c.id)) return;
  void send(api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments/{comment_id}", { params: { path: commentPath(c) } })).catch(
    (e) => {
      failed("Deleting the comment", e);
      void reloadComments(c);
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
    void reloadComments(c);
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
