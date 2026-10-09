// The API behind the store. Signed in, /w/{slug} of one of your workspaces loads it from the API
// into the same shapes the screens read (src/data/types.ts), so screens don't change; the demo
// workspace (/w/dotrix, seeded) stays in this browser. Writes go to the API as they happen:
// the store changes first (the screen answers at once), then the request; a refused request
// puts the item back as the API has it and says why.
//
// Wired: the workspace, members and roles, teams (who and which projects), projects (create,
// edit, status, star), issues (create, every field, checklists, repeats, stars, attachments,
// comments), notifications (read state), activity, agents (the list), Knowledge (read and save),
// files (upload, list, rename, duplicate, delete), automations (list, on/off, add a preset), the audit log.
// Changes made through mutate() anywhere in the screens (a sub-task ticked, a star, a team's
// people) are compared with what the API last had after each change (reconcile) and sent.
// Archive, delete, and moving an issue to another project go to the API too (a delete can't be
// undone there, so it offers no undo).
// Settings and Members (your account, the workspace, its people, agents' settings) are in
// account.ts. Not yet: chat and coding (their own step).
import { api, apiFetch, authPost, hasSession, problemMessage, unwrap, type Schemas } from "@/lib/api";

import { PCOLORS } from "../core/constants";
import { go } from "../core/nav";
import { fmtDate, uid } from "../core/utils";
import { fileType, fsize } from "../ui/helpers";
import { toast } from "../ui/toast";
import { AGENTS } from "./seed-dotrix";
import { D, S, afterMutate, persist, render } from "./store";
import type {
  Activity,
  Agent,
  Attachment,
  AuditEvent,
  Automation,
  Comment,
  Data,
  FileItem,
  KnowledgeFile,
  Member,
  Notif,
  NotifType,
  Project,
  Subtask,
  Task,
  Team,
} from "./types";

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
    archived: p.archived_at ? true : undefined,
  };
}

const RECUR_IN: Record<string, string> = { daily: "Daily", weekly: "Weekly", biweekly: "Every 2 weeks", monthly: "Monthly" };
const RECUR_OUT: Record<string, Schemas["Recurrence"]> = { Daily: "daily", Weekly: "weekly", "Every 2 weeks": "biweekly", Monthly: "monthly" };

const toSubtask = (c: Schemas["ChecklistItem"]): Subtask => ({ id: c.id, title: c.title, done: c.done ?? false, due: c.due ?? null, assignee: c.assignee_user_id ?? null });
const toChecklist = (subs: Subtask[]): Schemas["ChecklistItem"][] =>
  subs.map((x) => ({ id: x.id, title: x.title, done: x.done, due: x.due || null, assignee_user_id: x.assignee && fromApi(x.assignee) ? x.assignee : null }));
const toAttachment = (a: Schemas["AttachmentRead"]): Attachment => ({ id: a.id, name: a.filename, type: fileType(a.filename), size: fsize(a.size), by: a.uploaded_by_id ?? "", at: ms(a.created_at) });
/** Stand-ins for the attachments a list row only counts (cards show the count); the drawer loads the real ones. */
const counted = (n: number): Attachment[] => Array.from({ length: n }, (_, k) => ({ id: `counted-${k}`, name: "", type: "other", size: "", by: "", at: 0 }));
const toTeam = (t: Schemas["TeamRead"]): Team => ({ id: t.id, name: t.name, icon: t.icon, c: t.color, desc: t.description });

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
    subtasks: (i.checklist ?? []).map(toSubtask),
    attachments: "attachments" in i && i.attachments ? i.attachments.map(toAttachment) : counted(i.attachment_count ?? 0),
    deps: i.depends_on ?? [],
    desc: full ? mdToHtml(i.description) : "",
    estimate: i.estimate != null ? `${i.estimate}` : null,
    created: ms(i.created_at),
    updated: ms(i.updated_at),
    order,
    fav: false,
    recur: i.recurrence ? (RECUR_IN[i.recurrence] ?? null) : null,
    completedAt: i.status === "done" ? ms(i.updated_at) : undefined,
    archived: i.archived_at ? true : undefined,
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
const toAutomation = (a: Schemas["AutomationRead"]): Automation => ({ id: a.id, project: a.project_id, name: a.name, agent: AGENT_IN[a.agent] ?? a.agent, trigger: triggerLabel(a), enabled: a.enabled, unattended: a.unattended });

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
  // A built-in's look and role; a contract based on one keeps them.
  const look = AGENTS.find((x) => x.handle === handle) ?? AGENTS.find((x) => x.handle === (AGENT_IN[a.base ?? ""] ?? a.base));
  return {
    handle,
    name: a.name,
    role: look?.role ?? "Custom",
    desc: a.description,
    icon: look?.icon ?? "bot",
    c: look?.c ?? "#57544E",
    builtIn: a.source !== "custom",
    customised: a.source === "customised",
    tools: a.tools,
    model: a.model ?? undefined,
  };
}

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
      unwrap(api.GET("/v1/workspaces/{workspace_id}/issues", { params: { path: { workspace_id: ws.id }, query: { limit: 5000, order: "created", archived: "include" } } })),
      unwrap(api.GET("/v1/workspaces/{workspace_id}/notifications", { params: { path: { workspace_id: ws.id }, query: { limit: 200 } } })).catch(() => []),
      unwrap(api.GET("/v1/workspaces/{workspace_id}/activity", { params: { path: { workspace_id: ws.id }, query: { limit: 200, agents: true } } })).catch(() => []),
    ]);
    const stars = new Set((starred as { id: string }[]).map((p) => p.id));
    const ps = projects.map((p) => toProject(p, members, stars));
    // Per project: knowledge (every file's content), documents, automations. Agents and the audit
    // log are the workspace's; the audit log is for owners and admins, so others get none.
    const [perProject, agents, audit, teams, starredIssues] = await Promise.all([
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
      unwrap(api.GET("/v1/workspaces/{workspace_id}/teams", path)).catch(() => []),
      unwrap(api.GET("/v1/workspaces/{workspace_id}/issues", { params: { path: { workspace_id: ws.id }, query: { starred: true, limit: 5000 } } })).catch(() => []),
    ]);
    const teamList = teams as Schemas["TeamRead"][];
    const memberTeam = new Map(teamList.flatMap((t) => (t.member_ids ?? []).map((u) => [u, t.id] as const)));
    ps.forEach((p) => (p.team = teamList.find((t) => (t.project_ids ?? []).includes(p.id))?.id ?? ""));
    const starredKeys = new Set((starredIssues as Schemas["WorkspaceIssue"][]).map((i) => i.key));
    const data: Data = {
      ws: { id: ws.id, name: ws.name, c: hashTint(ws.id), plan: ws.kind === "personal" ? "Personal" : "Team", kind: ws.kind, url: ws.slug },
      workspaces: wss.map((w) => ({ id: w.id, name: w.name, c: hashTint(w.id), plan: w.kind === "personal" ? "Personal" : "Organisation", kind: w.kind, slug: w.slug })),
      me: me.id,
      members: members.map((m) => ({ ...toMember(m), team: memberTeam.get(m.user_id) ?? "" })),
      projects: ps,
      tasks: issues.map((i) => ({ ...toTask(i, i.project_id, i.rank), fav: starredKeys.has(i.key) })),
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
      teams: teamList.map(toTeam),
      agents: (agents as Schemas["AgentRead"][]).map(toAgent),
      threads: [],
      knowledge: perProject.flatMap((x) => x.knowledge),
      coding: [],
      audit: (audit as Schemas["AuditEventRead"][]).map(toAudit),
      automations: perProject.flatMap((x) => x.automations),
    };
    if (live.demo === null) live.demo = S.data; // set aside the demo's data the first time only
    S.data = data;
    baseline();
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
    const i = await unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(t.project), key: t.key } } }));
    Object.assign(t, toTask(i, t.project, t.order), { fav: t.fav });
    markTask(t);
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
  const was = synced.tasks.get(t.key);
  if (was && body.checklist) was.sub = subSig(t); // sent here, so reconcile doesn't send it again
  void unwrap(api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(t.project), key: t.key } }, body }))
    .then(async (i) => {
      t.updated = ms(i.updated_at);
      // A repeating issue just finished: the API made the next one.
      if (i.repeated_as && !D().tasks.some((x) => x.key === i.repeated_as)) {
        const next = await unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(t.project), key: i.repeated_as } } }));
        const nt = toTask(next, t.project, next.rank);
        D().tasks.push(nt);
        markTask(nt);
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
  const made = unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues", { params: { path: projectPath(t.project) }, body }))
    .then((i) => {
      const was = t.id;
      t.id = t.key = i.key;
      if (S.ui.drawer === was) S.ui.drawer = i.key;
      D().activity.forEach((a) => a.task === was && (a.task = i.key));
      markTask(t);
      render();
      // Starred while it was being created.
      if (t.fav) reconcile();
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
    const i = await unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(t.project), key: t.key } } }));
    const cs: Comment[] = (i.log ?? [])
      .filter((e) => e.kind === "commented" && e.body)
      .map((e) => ({ id: e.id, task: t.id, by: actor(e.author_user_id, e.author_agent), at: ms(e.created_at), text: e.body!, re: e.reactions ?? {} }));
    D().comments = [...D().comments.filter((c) => c.task !== t.id), ...cs];
    // The full issue has the description and its attachments, which lists leave out.
    if (!t.desc) t.desc = mdToHtml(i.description);
    t.attachments = (i.attachments ?? []).map(toAttachment);
    const was = synced.tasks.get(t.key);
    if (was) was.att = t.attachments.map((a) => a.id);
    render();
  } catch {
    /* the drawer still shows what the list had */
  }
}

export function commentPosted(t: Task, text: string, mentions: string[] = []) {
  if (!isLive()) return;
  void unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments", { params: { path: { ...projectPath(t.project), key: t.key } }, body: { body: text, mentions } }))
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
  }
  if (!Object.keys(body).length) return Promise.resolve();
  return unwrap(api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}", { params: { path: projectPath(p.id) }, body })).then(
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

/** An automation switched on or off, or let act without approval, in Settings (the store already shows it). */
export function automationToggled(a: Automation, field: "enabled" | "unattended" = "enabled") {
  if (!isLive()) return;
  void unwrap(api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/automations/{automation_id}", { params: { path: { ...projectPath(a.project), automation_id: a.id } }, body: { [field]: !!a[field] } })).catch((e) => {
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
  void unwrap(api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/documents/{document_id}", { ...docPath(f), body: { filename: f.name } }))
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
    const d = await unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/documents/{document_id}/duplicate", docPath(f)));
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
  void unwrap(api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/documents/{document_id}", docPath(f)))
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
  const i = await upload<Schemas["IssueRead"]>(`/v1/workspaces/${wsId()}/projects/${t.project}/issues/${encodeURIComponent(t.key)}/attachments`, file, onProgress);
  t.attachments = (i.attachments ?? []).map(toAttachment);
  const was = synced.tasks.get(t.key);
  if (was) was.att = t.attachments.map((a) => a.id);
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

/* ---------- what the API last had: changes made anywhere are compared with it and sent ---------- */

const synced = {
  tasks: new Map<string, { sub: string; fav: boolean; att: string[]; arch: boolean }>(), // by key: undo puts back copies
  projects: new Map<string, boolean>(), // archived
  teams: new Map<string, string>(),
  memberTeam: new Map<string, string>(),
  projectTeam: new Map<string, string>(),
};
const subSig = (t: Task) => JSON.stringify(toChecklist(t.subtasks));
const teamSig = (t: Team) => JSON.stringify([t.name, t.desc, t.icon, t.c]);
function markTask(t: Task) {
  synced.tasks.set(t.key, { sub: subSig(t), fav: t.fav, att: t.attachments.map((a) => a.id), arch: Boolean(t.archived) });
}
function markTeams() {
  synced.teams = new Map((D().teams ?? []).filter((t) => fromApi(t.id)).map((t) => [t.id, teamSig(t)]));
  synced.memberTeam = new Map(D().members.map((m) => [m.id, m.team]));
  synced.projectTeam = new Map(D().projects.map((p) => [p.id, p.team]));
}
function baseline() {
  synced.tasks = new Map();
  D().tasks.forEach(markTask);
  synced.projects = new Map(D().projects.map((p) => [p.id, Boolean(p.archived)]));
  markTeams();
}

/** After every change in a real workspace: send what differs from what the API last had. */
function reconcile() {
  if (!isLive()) return;
  for (const t of D().tasks) {
    const was = synced.tasks.get(t.key);
    if (!was || t.key.startsWith("new-")) continue; // not on the API yet: creating it sends it
    const path = { params: { path: { ...projectPath(t.project), key: t.key } } };
    const sub = subSig(t);
    if (sub !== was.sub) {
      was.sub = sub;
      void unwrap(api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { ...path, body: { checklist: toChecklist(t.subtasks) } })).catch((e) => {
        failed(`The checklist of “${t.title}”`, e);
        void reloadTask(t);
      });
    }
    if (t.fav !== was.fav) {
      was.fav = t.fav;
      const on = t.fav;
      void unwrap(on ? api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/star", path) : api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/star", path)).catch((e) => {
        failed("The star", e);
        t.fav = was.fav = !on;
        render();
      });
    }
    if (Boolean(t.archived) !== was.arch) {
      was.arch = Boolean(t.archived);
      void unwrap(api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { ...path, body: { archived: was.arch } })).catch((e) => {
        failed(`“${t.title}”`, e);
        void reloadTask(t);
      });
    }
    const gone = was.att.filter((id) => !id.startsWith("counted-") && !t.attachments.some((a) => a.id === id));
    was.att = t.attachments.map((a) => a.id);
    for (const id of gone)
      void unwrap(api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/attachments/{attachment_id}", { params: { path: { ...path.params.path, attachment_id: id } } })).catch((e) => {
        failed("Removing the file", e);
        void reloadTask(t);
      });
  }
  for (const pr of D().projects) {
    const was = synced.projects.get(pr.id);
    if (was === undefined || Boolean(pr.archived) === was) continue;
    synced.projects.set(pr.id, Boolean(pr.archived));
    void unwrap(api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}", { params: { path: projectPath(pr.id) }, body: { archived: Boolean(pr.archived) } })).catch((e) => {
      failed(pr.name, e);
      void reloadProjects();
    });
  }
  reconcileTeams();
}
afterMutate.push(reconcile);
/** Run after the store's data was replaced (undo): what differs from the API is sent. */
export const resynced = () => reconcile();

/* ---------- delete, move, comments ---------- */

/** Issues deleted in the screens (already gone from the store). A delete can't be undone. */
export function tasksDeleted(ts: Task[]) {
  if (!isLive()) return;
  for (const t of ts) {
    if (t.key.startsWith("new-")) continue;
    synced.tasks.delete(t.key);
    void unwrap(api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(t.project), key: t.key } } })).catch(async (e) => {
      failed(`Deleting “${t.title}”`, e);
      try {
        // Put it back as the API has it.
        const i = await unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params: { path: { ...projectPath(t.project), key: t.key } } }));
        const back = { ...toTask(i, t.project, t.order), fav: t.fav };
        D().tasks.push(back);
        markTask(back);
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
  synced.projects.delete(pr.id);
  void unwrap(api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}", { params: { path: projectPath(pr.id) } })).catch((e) => {
    failed(`Deleting ${pr.name}`, e);
    void reloadProjects();
  });
}

/** Move an issue to another project: the API creates it there (next key, its history with it) and
 * deletes it here; the store's task becomes the new one. */
export async function taskMoved(t: Task, toProject: string) {
  const from = t.key;
  try {
    const i = await unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/move", { params: { path: { ...projectPath(t.project), key: from } }, body: { project_id: toProject } }));
    synced.tasks.delete(from);
    Object.assign(t, toTask(i, toProject, t.order), { fav: t.fav });
    markTask(t);
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
  void unwrap(api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments/{comment_id}", { params: { path: commentPath(c) }, body: { body: c.text } })).catch((e) => {
    failed("Your comment", e);
    void reloadComments(c);
  });
}
/** A comment deleted (already gone from the store). */
export function commentDeleted(c: Comment) {
  if (!isLive() || !fromApi(c.id)) return;
  void unwrap(api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments/{comment_id}", { params: { path: commentPath(c) } })).catch((e) => {
    failed("Deleting the comment", e);
    void reloadComments(c);
  });
}
/** Your reaction added or taken back (the store shows it already). */
export function commentReacted(c: Comment, emoji: string, on: boolean) {
  if (!isLive() || !fromApi(c.id)) return;
  const path = { params: { path: { ...commentPath(c), emoji } } };
  void unwrap(on ? api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments/{comment_id}/reactions/{emoji}", path) : api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments/{comment_id}/reactions/{emoji}", path)).catch((e) => {
    failed("Your reaction", e);
    void reloadComments(c);
  });
}

const teamPath = (id: string) => ({ workspace_id: wsId(), team_id: id });
const pendingTeams = new WeakSet<Team>();

async function reloadTeams() {
  try {
    const teams = await unwrap(api.GET("/v1/workspaces/{workspace_id}/teams", { params: { path: { workspace_id: wsId() } } }));
    D().teams = teams.map(toTeam);
    D().members.forEach((m) => (m.team = teams.find((t) => (t.member_ids ?? []).includes(m.id))?.id ?? ""));
    D().projects.forEach((p) => (p.team = teams.find((t) => (t.project_ids ?? []).includes(p.id))?.id ?? ""));
    markTeams();
    render();
  } catch {
    /* leave what's shown */
  }
}
function teamFailed(what: string, e: unknown) {
  failed(what, e);
  void reloadTeams();
}

function reconcileTeams() {
  const teams = D().teams ?? [];
  for (const tm of teams) {
    if (!fromApi(tm.id)) {
      if (!pendingTeams.has(tm)) {
        pendingTeams.add(tm);
        void createTeam(tm);
      }
      continue;
    }
    const sig = teamSig(tm);
    if (synced.teams.get(tm.id) !== sig) {
      synced.teams.set(tm.id, sig);
      void unwrap(api.PATCH("/v1/workspaces/{workspace_id}/teams/{team_id}", { params: { path: teamPath(tm.id) }, body: { name: tm.name, description: tm.desc, icon: tm.icon, color: tm.c } })).catch((e) => teamFailed(tm.name, e));
    }
  }
  for (const id of [...synced.teams.keys()])
    if (!teams.some((t) => t.id === id)) {
      synced.teams.delete(id);
      void unwrap(api.DELETE("/v1/workspaces/{workspace_id}/teams/{team_id}", { params: { path: teamPath(id) } })).catch((e) => teamFailed("Deleting the team", e));
    }
  // Who is in which team, and which project is under which: one team each.
  for (const m of D().members) {
    const now = m.team || "";
    const was = synced.memberTeam.get(m.id) ?? "";
    if (!fromApi(m.id) || now === was || (now && !fromApi(now))) continue; // a team being created: sent once it exists
    synced.memberTeam.set(m.id, now);
    const req = now
      ? api.PUT("/v1/workspaces/{workspace_id}/teams/{team_id}/members/{user_id}", { params: { path: { ...teamPath(now), user_id: m.id } } })
      : api.DELETE("/v1/workspaces/{workspace_id}/teams/{team_id}/members/{user_id}", { params: { path: { ...teamPath(was), user_id: m.id } } });
    void unwrap(req).catch((e) => teamFailed(`${m.name}'s team`, e));
  }
  for (const p of D().projects) {
    const now = p.team || "";
    const was = synced.projectTeam.get(p.id) ?? "";
    if (!fromApi(p.id) || now === was || (now && !fromApi(now))) continue;
    synced.projectTeam.set(p.id, now);
    const req = now
      ? api.PUT("/v1/workspaces/{workspace_id}/teams/{team_id}/projects/{project_id}", { params: { path: { ...teamPath(now), project_id: p.id } } })
      : api.DELETE("/v1/workspaces/{workspace_id}/teams/{team_id}/projects/{project_id}", { params: { path: { ...teamPath(was), project_id: p.id } } });
    void unwrap(req).catch((e) => teamFailed(`${p.name}'s team`, e));
  }
}

async function createTeam(tm: Team) {
  try {
    const made = await unwrap(api.POST("/v1/workspaces/{workspace_id}/teams", { params: { path: { workspace_id: wsId() } }, body: { name: tm.name, description: tm.desc, icon: tm.icon, color: tm.c } }));
    const old = tm.id;
    tm.id = made.id;
    D().members.forEach((m) => m.team === old && (m.team = made.id));
    D().projects.forEach((p) => p.team === old && (p.team = made.id));
    synced.teams.set(made.id, teamSig(tm));
    if (location.pathname.includes(old)) go("team", { id: made.id }, { replace: true });
    reconcile(); // its people and projects, now that it exists
    render();
  } catch (e) {
    failed(tm.name, e);
    void reloadTeams();
  }
}

/* ---------- a new organisation (onboarding, or "Create workspace" in the switcher) ---------- */

const PROJECT_ICONS = new Set(["globe", "smartphone", "megaphone", "rocket", "component", "building-2", "layout-grid", "palette", "code", "briefcase", "target", "layers", "zap", "heart", "folder", "sparkles"]);

/** Create an organisation with its first project (and the template's starter issues), invite
 * people, and return its slug to open. Signed in only; the demo keeps the seeded flow. */
export async function organisationCreated(f: { name: string; project: string; icon: string; tasks: string[]; invites: string[] }): Promise<string> {
  const ws = await unwrap(api.POST("/v1/workspaces", { body: { name: f.name, kind: "organization" } }));
  const inWs = { params: { path: { workspace_id: ws.id } } };
  const letters = f.project.toUpperCase().replace(/[^A-Z ]/g, "");
  let key = letters.split(/\s+/).filter(Boolean).map((w) => w[0]).join("").slice(0, 4);
  if (key.length < 2) key = (letters.replace(/\s/g, "") + "PRJ").slice(0, 3);
  const project = await unwrap(
    api.POST("/v1/workspaces/{workspace_id}/projects", {
      ...inWs,
      body: { key, name: f.project, description: "", source: "docs_only", access: "workspace", icon: PROJECT_ICONS.has(f.icon) ? f.icon : "folder" },
    }),
  );
  const inProject = { params: { path: { workspace_id: ws.id, project_id: project.id } } };
  for (const title of f.tasks) // one at a time, so keys follow the template's order
    await unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues", {
        ...inProject,
        body: { title, type: "task", description: "", status: "todo", priority: "none", depends_on: [], labels: [], components: [], links: [], checklist: [], parent: null },
      }),
    );
  for (const email of f.invites)
    await unwrap(api.POST("/v1/workspaces/{workspace_id}/invites", { ...inWs, body: { email, role: "member" } })).catch((e) => failed(`The invite to ${email}`, e));
  return ws.slug;
}
