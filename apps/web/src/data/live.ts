// The API behind the store. Signed in, /w/{slug} of one of your workspaces loads it from the API
// into the same shapes the screens read (src/data/types.ts), so screens don't change; the demo
// workspace (/w/dotrix, seeded) stays in this browser. Writes go to the API as they happen:
// the store changes first (the screen answers at once), then the request; a refused request
// puts the item back as the API has it and says why.
//
// Wired: the workspace, members and roles, projects (create, edit, status, star), issues
// (create, every field the API has, comments), notifications (read state), activity, agents
// (the list), Knowledge (read and save), files (upload, list), automations (list, on/off, add
// a preset), the audit log.
// Not yet: chat and coding (their own step); teams, sub-task checklists, attachments on issues,
// repeats, starring an issue, renaming or duplicating files, and custom agents stay in this browser.
import { api, apiFetch, authPost, hasSession, problemMessage, unwrap, type Schemas } from "@/lib/api";

import { PCOLORS } from "../core/constants";
import { uid } from "../core/utils";
import { fileType, fsize } from "../ui/helpers";
import { toast } from "../ui/toast";
import { AGENTS } from "./seed-dotrix";
import { D, S, persist, render } from "./store";
import type { Activity, Agent, AuditEvent, Automation, Comment, Data, FileItem, KnowledgeFile, Member, Notif, NotifType, Project, Task } from "./types";

type W = Schemas["WorkspaceWithRole"];

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
// While a real workspace is shown, this browser keeps saving the demo's data, never the API's.
persist.data = () => (live.mode === "demo" ? S.data : (live.demo ?? S.data));
/** An id the API made (a project or user), not one the store made up for a new item. */
const fromApi = (id: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-/.test(id);

/* ---------- mapping the API into the store's shapes ---------- */

const STATUS_IN: Record<string, Task["status"]> = { backlog: "backlog", todo: "todo", in_progress: "progress", blocked: "blocked", review: "review", done: "done" };
const STATUS_OUT: Record<Task["status"], Schemas["IssueStatus"]> = { backlog: "backlog", todo: "todo", progress: "in_progress", blocked: "blocked", review: "review", done: "done" };
const ROLE_IN: Record<string, Member["role"]> = { owner: "Owner", admin: "Admin", member: "Member", guest: "Guest" };
const AGENT_IN: Record<string, string> = { "project-manager": "auto", pm: "auto", auto: "auto" };
const TINTS = Object.values(PCOLORS);

const hashTint = (s: string) => TINTS[[...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7) % TINTS.length]!;
const ms = (s: string | null | undefined) => (s ? new Date(s).getTime() : Date.now());
/** An agent or coding tool as the store names it ("auto", "research", "agent:claude-code"). */
const agentId = (a: string | null | undefined) => (a ? (a.includes("code") || a === "codex" ? `agent:${a === "coding-agent" ? "claude-code" : a}` : (AGENT_IN[a] ?? a)) : null);
const actor = (user: string | null | undefined, agent: string | null | undefined) => user ?? agentId(agent) ?? "";

/** Markdown from the API, shown by the drawer's rich text (HTML). Plain paragraphs and lists. */
function mdToHtml(md: string): string {
  const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
  const inline = (s: string) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>");
  return md
    .trim()
    .split(/\n{2,}/)
    .map((block) => {
      const lines = block.split("\n");
      if (lines.every((l) => /^\s*[-*] /.test(l))) return `<ul>${lines.map((l) => `<li>${inline(l.replace(/^\s*[-*] /, ""))}</li>`).join("")}</ul>`;
      if (lines.every((l) => /^\s*\d+\. /.test(l))) return `<ol>${lines.map((l) => `<li>${inline(l.replace(/^\s*\d+\. /, ""))}</li>`).join("")}</ol>`;
      return `<p>${lines.map(inline).join("<br>")}</p>`;
    })
    .join("");
}
/** The drawer's HTML back to Markdown for the API. */
export function htmlToMd(html: string): string {
  const el = document.createElement("div");
  el.innerHTML = html;
  const walk = (n: Node): string => {
    if (n.nodeType === Node.TEXT_NODE) return n.textContent ?? "";
    const e = n as HTMLElement;
    const kids = [...e.childNodes].map(walk).join("");
    switch (e.tagName) {
      case "B":
      case "STRONG":
        return `**${kids}**`;
      case "I":
      case "EM":
        return `*${kids}*`;
      case "CODE":
        return `\`${kids}\``;
      case "BR":
        return "\n";
      case "LI":
        return e.parentElement?.tagName === "OL" ? `${[...e.parentElement.children].indexOf(e) + 1}. ${kids}\n` : `- ${kids}\n`;
      case "UL":
      case "OL":
        return `${kids}\n`;
      case "P":
      case "DIV":
      case "H1":
      case "H2":
      case "H3":
        return `${kids}\n\n`;
      default:
        return kids;
    }
  };
  return walk(el).replace(/\n{3,}/g, "\n\n").trim();
}

function toMember(m: Schemas["MemberRead"]): Member {
  return { id: m.user_id, name: m.display_name, email: m.email, role: ROLE_IN[m.role] ?? "Member", team: "", title: m.title ?? "", c: hashTint(m.user_id), status: "active", last: null, tz: "" };
}

function toProject(p: Schemas["ProjectRead"], members: Schemas["MemberRead"][], starred: Set<string>): Project {
  const status: Project["status"] =
    p.status === "completed" ? "complete" : p.status === "on_hold" ? "hold" : p.status === "planning" ? "planning" : p.health === "at_risk" || p.health === "off_track" ? "risk" : "active";
  const seeing = members.filter((m) => m.sees_all_projects || m.project_ids.includes(p.id)).map((m) => m.user_id);
  const owner = members.find((m) => m.role === "owner")?.user_id ?? seeing[0] ?? "";
  return {
    id: p.id,
    key: p.key,
    name: p.name,
    icon: p.icon ?? "folder",
    color: p.color ?? Object.keys(PCOLORS)[[...p.key].reduce((a, c) => a + c.charCodeAt(0), 0) % TINTS.length]!,
    status,
    team: "",
    lead: owner,
    due: p.target_date ?? "",
    start: p.created_at.slice(0, 10),
    fav: starred.has(p.id),
    members: seeing,
    desc: p.description || "No description yet.",
    milestones: [],
    last: Math.max(0, Math.round((Date.now() - ms(p.updated_at)) / 60000)),
    private: p.access === "restricted",
    repo: p.repo_url ?? undefined,
    model: p.model,
  };
}

type IssueLike = Schemas["WorkspaceIssue"] | (Schemas["IssueRead"] & { project_id?: string });
function toTask(i: IssueLike, projectId: string, order: number): Task {
  const full = "description" in i;
  return {
    id: i.key,
    key: i.key,
    project: projectId,
    title: i.title,
    status: STATUS_IN[i.status] ?? "todo",
    assignee: i.assignee_user_id ?? agentId(i.assignee_agent),
    priority: i.priority,
    due: i.due,
    start: i.scheduled ?? null,
    labels: i.labels,
    subtasks: [],
    attachments: [],
    deps: i.depends_on ?? [],
    desc: full ? mdToHtml(i.description) : "",
    estimate: i.estimate != null ? `${i.estimate}` : null,
    created: ms(i.created_at),
    updated: ms(i.updated_at),
    order,
    fav: false,
    recur: null,
    completedAt: i.status === "done" ? ms(i.updated_at) : undefined,
    type: i.type,
    parent: i.parent_key ?? null,
  };
}

const NOTIF_IN: Record<string, NotifType> = { assigned: "assign", mention: "mention", watching: "update", approval: "approval", checkpoint: "checkpoint", finding: "finding", decided: "decided" };
function toNotif(n: Schemas["NotificationRead"]): Notif {
  return {
    id: n.id,
    type: NOTIF_IN[n.kind] ?? "update",
    by: n.actor_user_id ?? agentId(n.actor_agent),
    task: n.issue_key ?? undefined,
    project: n.project_id,
    thread: n.thread_id ?? undefined,
    text: n.title,
    snippet: n.excerpt ?? "",
    at: ms(n.created_at),
    read: n.read || n.resolved,
  };
}

function toActivity(a: Schemas["ActivityItem"]): Activity {
  const verb: Record<string, string> = {
    "issue.created": "created",
    "issue.updated": "updated",
    "issue.commented": "commented on",
    "issue.claimed": "started",
    "document.changed": "updated",
    "document.deleted": "deleted",
    "run.started": "asked the agents about",
    "approval.decided": a.decision === "rejected" ? "rejected a change to" : "approved a change to",
  };
  return {
    id: uid("a"),
    by: actor(a.actor_user_id, a.actor_agent),
    verb: verb[a.kind] ?? "updated",
    task: a.issue_key ?? null,
    project: a.project_id,
    at: ms(a.at),
    extra: a.path ?? (a.kind.startsWith("run.") || a.kind.startsWith("approval.") ? (a.target ?? a.project_name) : ""),
  };
}

const SCHEDULE_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const EVENT_LABEL: Record<string, string> = {
  "issue.created": "When an issue is created",
  "issue.done": "When an issue is done",
  "document.changed": "When a document changes",
  "changes.approved": "When changes are approved",
  "code.pushed": "When code is pushed",
};
const hour = (h: number) => `${String(h).padStart(2, "0")}:00`;

/** An automation's trigger as the screens say it ("Weekly, Monday 08:00 · When an issue is created"). */
function triggerLabel(a: Schemas["AutomationRead"]): string {
  const parts = a.events.map((e) => EVENT_LABEL[e] ?? e);
  if (a.schedule_hour != null) parts.unshift(a.schedule_weekday != null ? `Weekly, ${SCHEDULE_DAYS[a.schedule_weekday]} ${hour(a.schedule_hour)}` : `Daily, ${hour(a.schedule_hour)}`);
  return parts.join(" · ") || "Run by hand";
}
const toAutomation = (a: Schemas["AutomationRead"]): Automation => ({ id: a.id, project: a.project_id, name: a.name, agent: AGENT_IN[a.agent] ?? a.agent, trigger: triggerLabel(a), enabled: a.enabled });

function toKnowledge(f: Schemas["FileRead"], pid: string): KnowledgeFile {
  return { path: f.path, project: pid, content: f.content, version: f.version, by: "", at: ms(f.updated_at) };
}
function toFile(d: Schemas["DocumentRead"], pid: string): FileItem {
  return {
    id: d.id,
    project: pid,
    name: d.filename,
    type: fileType(d.filename),
    size: fsize(d.size),
    by: d.uploaded_by_id ?? "",
    at: ms(d.created_at),
    converted: d.status === "ready" ? "ready" : d.status === "failed" ? "failed" : "converting",
  };
}
const toAudit = (a: Schemas["AuditEventRead"]): AuditEvent => ({
  id: a.id,
  at: ms(a.created_at),
  by: actor(a.actor_user_id, a.agent),
  action: a.action,
  target: a.target ?? "",
  project: a.project_id ?? undefined,
});
/** An agent as the store has it: the API's definition, with the store's icon and colour for it. */
function toAgent(a: Schemas["AgentRead"]): Agent {
  const handle = AGENT_IN[a.handle] ?? a.handle;
  const look = AGENTS.find((x) => x.handle === handle);
  return {
    handle,
    name: a.name,
    desc: a.description,
    icon: look?.icon ?? "bot",
    c: look?.c ?? "#57544E",
    builtIn: a.source !== "custom",
    customised: a.source === "customised",
    tools: a.tools,
    model: a.model ?? undefined,
  };
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
        unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/knowledge/files/{path}", { params: { path: { ...path, path: f.path } } })).then((r) => toKnowledge(r, pid)),
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
    const [members, projects, starred, issues, notifs, activity] = await Promise.all([
      unwrap(api.GET("/v1/workspaces/{workspace_id}/members", path)),
      unwrap(api.GET("/v1/workspaces/{workspace_id}/projects", path)),
      unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/starred", path)).catch(() => []),
      unwrap(api.GET("/v1/workspaces/{workspace_id}/issues", { params: { path: { workspace_id: ws.id }, query: { limit: 5000, order: "created" } } })),
      unwrap(api.GET("/v1/workspaces/{workspace_id}/notifications", { params: { path: { workspace_id: ws.id }, query: { limit: 200 } } })).catch(() => []),
      unwrap(api.GET("/v1/workspaces/{workspace_id}/activity", { params: { path: { workspace_id: ws.id }, query: { limit: 200, agents: true } } })).catch(() => []),
    ]);
    const stars = new Set((starred as { id: string }[]).map((p) => p.id));
    const ps = projects.map((p) => toProject(p, members, stars));
    // Per project: knowledge (every file's content), documents, automations. Agents and the audit
    // log are the workspace's; the audit log is for owners and admins, so others get none.
    const [perProject, agents, audit] = await Promise.all([
      Promise.all(
        projects.map(async (p) => {
          const pp = { params: { path: { workspace_id: ws.id, project_id: p.id } } };
          const [files, docs, autos] = await Promise.all([
            loadKnowledge(ws.id, p.id).catch(() => []),
            unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/documents", pp)).catch(() => []),
            unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/automations", pp)).catch(() => []),
          ]);
          return { knowledge: files, files: docs.map((d) => toFile(d, p.id)), automations: autos.map(toAutomation) };
        }),
      ),
      unwrap(api.GET("/v1/workspaces/{workspace_id}/agents", path)).catch(() => []),
      unwrap(api.GET("/v1/workspaces/{workspace_id}/audit", { params: { path: { workspace_id: ws.id }, query: { limit: 200 } } })).catch(() => []),
    ]);
    const data: Data = {
      ws: { id: ws.id, name: ws.name, c: hashTint(ws.id), plan: ws.kind === "personal" ? "Personal" : "Team", kind: ws.kind, url: ws.slug },
      workspaces: wss.map((w) => ({ id: w.id, name: w.name, c: hashTint(w.id), plan: w.kind === "personal" ? "Personal" : "Organisation", kind: w.kind, slug: w.slug })),
      me: me.id,
      members: members.map(toMember),
      projects: ps,
      tasks: issues.map((i) => toTask(i, i.project_id, i.rank)),
      comments: [],
      activity: activity.map(toActivity),
      notifs: notifs.map(toNotif),
      files: perProject.flatMap((x) => x.files),
      events: [],
      projOrder: [...ps.filter((p) => p.fav), ...ps.filter((p) => !p.fav)].map((p) => p.id),
      savedViews: [],
      recentSearches: [],
      sessions: [],
      invoices: [],
      tfa: false,
      notifPrefs: {},
      teams: [],
      agents: (agents as Schemas["AgentRead"][]).map(toAgent),
      threads: [],
      knowledge: perProject.flatMap((x) => x.knowledge),
      coding: [],
      audit: (audit as Schemas["AuditEventRead"][]).map(toAudit),
      automations: perProject.flatMap((x) => x.automations),
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
    const i = await unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(t.project), key: t.key } } }));
    Object.assign(t, toTask(i, t.project, t.order), { subtasks: t.subtasks, attachments: t.attachments, fav: t.fav, recur: t.recur });
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
  if (keys.includes("project")) toast("Moving an issue to another project isn't saved yet", { kind: "info" });
  void unwrap(api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(t.project), key: t.key } }, body }))
    .then((i) => {
      t.updated = ms(i.updated_at);
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
  const full = issueFields(t, ["status", "priority", "assignee", "due", "start", "labels", "deps", "type", "estimate", "desc"]);
  const { components: _c, links: _l, ...rest } = full;
  const body: Schemas["IssueCreate"] = {
    ...rest,
    title: t.title,
    type: t.type,
    description: full.description ?? "",
    depends_on: full.depends_on ?? [],
    labels: full.labels ?? [],
    status: full.status ?? "todo",
    priority: full.priority ?? "none",
    parent: t.parent ?? null,
  };
  return unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues", { params: { path: projectPath(t.project) }, body }))
    .then((i) => {
      const was = t.id;
      t.id = t.key = i.key;
      if (S.ui.drawer === was) S.ui.drawer = i.key;
      D().activity.forEach((a) => a.task === was && (a.task = i.key));
      render();
    })
    .catch((e) => {
      failed(`“${t.title}”`, e);
      D().tasks = D().tasks.filter((x) => x !== t);
      render();
    });
}

/** Comments of an issue, when its drawer opens. */
export async function loadComments(t: Task) {
  if (!isLive() || t.key.startsWith("new-")) return;
  try {
    const i = await unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(t.project), key: t.key } } }));
    const cs: Comment[] = (i.log ?? [])
      .filter((e) => e.kind === "commented" && e.body)
      .map((e) => ({ id: uid("c"), task: t.id, by: actor(e.author_user_id, e.author_agent), at: ms(e.created_at), text: e.body!, re: {} }));
    D().comments = [...D().comments.filter((c) => c.task !== t.id), ...cs];
    // The full issue has the description, which lists leave out.
    if (!t.desc) t.desc = mdToHtml(i.description);
    render();
  } catch {
    /* the drawer still shows what the list had */
  }
}

export function commentPosted(t: Task, text: string, mentions: string[] = []) {
  if (!isLive()) return;
  void unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments", { params: { path: { ...projectPath(t.project), key: t.key } }, body: { body: text, mentions } })).catch((e) => failed("Your comment", e));
}

/** A rank change in a list or on the board: place it before the issue that now follows it. */
export function taskRanked(t: Task, before: Task | undefined, after: Task | undefined) {
  if (!isLive() || (!before && !after)) return;
  const body = before ? { before: before.key } : { after: after!.key };
  void unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/rank", { params: { path: { ...projectPath(t.project), key: t.key } }, body: body as Schemas["RankRequest"] })).catch((e) => failed("The new order", e));
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

export function projectChanged(p: Project, keys: (keyof Project)[]) {
  if (!isLive()) return;
  const body: Schemas["ProjectUpdate"] = {};
  for (const k of keys) {
    if (k === "name") body.name = p.name;
    else if (k === "desc") body.description = p.desc;
    else if (k === "icon") body.icon = p.icon;
    else if (k === "color") body.color = p.color as Schemas["ProjectColor"];
    else if (k === "due") body.target_date = p.due || null;
    else if (k === "status") Object.assign(body, PSTATUS_OUT[p.status]);
    else if (k === "private") body.access = p.private ? "restricted" : "workspace";
  }
  if (!Object.keys(body).length) return;
  void unwrap(api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}", { params: { path: projectPath(p.id) }, body })).catch((e) => {
    failed(p.name, e);
    void reloadProjects();
  });
}

export function projectCreated(p: Project) {
  if (!isLive()) return;
  const was = p.id;
  void unwrap(
    api.POST("/v1/workspaces/{workspace_id}/projects", {
      params: { path: { workspace_id: wsId() } },
      body: { key: p.key, name: p.name, source: "docs_only", description: p.desc === "No description yet." ? "" : p.desc, icon: p.icon, color: p.color as Schemas["ProjectColor"], access: p.private ? "restricted" : "workspace" },
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
  void unwrap(p.fav ? api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/star", params) : api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/star", params)).catch((e) => failed("The star", e));
}

export function roleChanged(m: Member) {
  if (!isLive()) return;
  void unwrap(api.PATCH("/v1/workspaces/{workspace_id}/members/{user_id}", { params: { path: { workspace_id: wsId(), user_id: m.id } }, body: { role: m.role.toLowerCase() as Schemas["Role"] } })).catch((e) => {
    failed(`${m.name}'s role`, e);
    void reloadProjects();
  });
}

export function notifsRead(ids: string[] | "all") {
  if (!isLive() || (ids !== "all" && !ids.length)) return;
  void unwrap(api.POST("/v1/workspaces/{workspace_id}/notifications/read", { params: { path: { workspace_id: wsId() } }, body: ids === "all" ? { all: true, ids: [] } : { ids, all: false } })).catch(() => undefined);
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
  void unwrap(
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

/** An automation switched on or off in Settings (the store already shows it). */
export function automationToggled(a: Automation) {
  if (!isLive()) return;
  void unwrap(api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/automations/{automation_id}", { params: { path: { ...projectPath(a.project), automation_id: a.id } }, body: { enabled: a.enabled } })).catch((e) => {
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
  "Triage new bugs": { agent: "auto", events: ["issue.created"], instructions: "For each new issue, check for duplicates and fill in missing fields, as changes to approve." },
  "Watch a topic": { agent: "research", weekly: true, instructions: "Re-check the topic against the newest research note and report what changed, with sources." },
};

/** A preset added in Settings: created for the project, then shown. */
export async function automationAdded(pid: string, preset: string) {
  const spec = PRESETS[preset];
  if (!spec || !isLive()) return;
  try {
    const made = await unwrap(
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
          max_runs_per_day: 3,
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
  const body = new FormData();
  body.append("file", file);
  onProgress(15);
  const res = await apiFetch(`/v1/workspaces/${wsId()}/projects/${pid}/documents`, { method: "POST", body });
  if (!res.ok) {
    const problem = (await res.json().catch(() => undefined)) as Parameters<typeof problemMessage>[0];
    throw new Error(problemMessage(problem) ?? "The file didn't upload");
  }
  const doc = (await res.json()) as Schemas["DocumentRead"];
  D().files.unshift(toFile(doc, pid));
  render();
  onProgress(100);
}
