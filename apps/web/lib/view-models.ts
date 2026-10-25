// Maps the API's schemas into the store's view types (Task, Project, Member, ...), both
// ways. Used by the TanStack hooks that feed the screens and by live.ts while it still
// fills the store — one conversion layer, whichever side of the migration a surface is on.
import type { Schemas } from "@dotrix/api-client";

import { PCOLORS } from "@/src/core/constants";
import { uid } from "@/src/core/utils";
import { htmlToMd, mdToHtml } from "@/src/data/markdown";
import { AGENTS } from "@/src/data/seed-dotrix";
import type {
  Activity,
  Agent,
  Attachment,
  AuditEvent,
  Automation,
  CodingSession,
  FileItem,
  KnowledgeFile,
  Member,
  Notif,
  NotifType,
  Project,
  Subtask,
  Task,
  Thread,
} from "@/src/data/types";
import { fileType, fsize } from "@/src/ui/helpers";

/** An id the API made (a project or user), not one the store made up for a new item. */
export const fromApi = (id: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-/.test(id);

export const STATUS_IN: Record<string, Task["status"]> = {
  backlog: "backlog",
  todo: "todo",
  in_progress: "progress",
  blocked: "blocked",
  review: "review",
  done: "done",
};
export const STATUS_OUT: Record<Task["status"], Schemas["IssueStatus"]> = {
  backlog: "backlog",
  todo: "todo",
  progress: "in_progress",
  blocked: "blocked",
  review: "review",
  done: "done",
};
export const ROLE_IN: Record<string, Member["role"]> = { owner: "Owner", admin: "Admin", member: "Member", guest: "Guest" };
export const AGENT_IN: Record<string, string> = { "project-manager": "auto", pm: "auto", auto: "auto" };
const TINTS = Object.values(PCOLORS);

export const hashTint = (s: string) => TINTS[[...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7) % TINTS.length]!;
export const ms = (s: string | null | undefined) => (s ? new Date(s).getTime() : Date.now());
/** An agent or Kai (the coding agent) as the store names it ("auto", "research", "agent:coding-agent"). */
const CODING_IDS = new Set(["coding-agent", "claude-code", "codex", "opencode"]);
export const agentId = (a: string | null | undefined) => (a ? (CODING_IDS.has(a) ? `agent:${a}` : (AGENT_IN[a] ?? a)) : null);
export const actor = (user: string | null | undefined, agent: string | null | undefined) => user ?? agentId(agent) ?? "";

export function toMember(m: Schemas["MemberRead"]): Member {
  return {
    id: m.user_id,
    name: m.display_name,
    email: m.email,
    role: ROLE_IN[m.role] ?? "Member",
    title: m.title ?? "",
    c: hashTint(m.user_id),
    status: "active",
    last: null,
    tz: "",
  };
}

export function toProject(p: Schemas["ProjectRead"], members: Schemas["MemberRead"][], starred: Set<string>): Project {
  const status: Project["status"] =
    p.status === "completed"
      ? "complete"
      : p.status === "on_hold"
        ? "hold"
        : p.status === "planning"
          ? "planning"
          : p.health === "at_risk" || p.health === "off_track"
            ? "risk"
            : "active";
  const seeing = members.filter((m) => m.sees_all_projects || m.project_ids.includes(p.id)).map((m) => m.user_id);
  const owner = members.find((m) => m.role === "owner")?.user_id ?? seeing[0] ?? "";
  return {
    id: p.id,
    key: p.key,
    name: p.name,
    icon: p.icon ?? "folder",
    color: p.color ?? Object.keys(PCOLORS)[[...p.key].reduce((a, c) => a + c.charCodeAt(0), 0) % TINTS.length]!,
    status,
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

export const RECUR_IN: Record<string, string> = { daily: "Daily", weekly: "Weekly", biweekly: "Every 2 weeks", monthly: "Monthly" };
export const RECUR_OUT: Record<string, Schemas["Recurrence"]> = {
  Daily: "daily",
  Weekly: "weekly",
  "Every 2 weeks": "biweekly",
  Monthly: "monthly",
};

export const toSubtask = (c: Schemas["ChecklistItem"]): Subtask => ({
  id: c.id,
  title: c.title,
  done: c.done ?? false,
  due: c.due ?? null,
  assignee: c.assignee_user_id ?? null,
});
export const toChecklist = (subs: Subtask[]): Schemas["ChecklistItem"][] =>
  subs.map((x) => ({ id: x.id, title: x.title, done: x.done, due: x.due || null, assignee_user_id: x.assignee && fromApi(x.assignee) ? x.assignee : null }));

export const toAttachment = (a: Schemas["AttachmentRead"]): Attachment => ({
  id: a.id,
  name: a.filename,
  type: fileType(a.filename),
  size: fsize(a.size),
  by: a.uploaded_by_id ?? "",
  at: ms(a.created_at),
});
/** Stand-ins for the attachments a list row only counts (cards show the count); the drawer loads the real ones. */
export const counted = (n: number): Attachment[] =>
  Array.from({ length: n }, (_, k) => ({ id: `counted-${k}`, name: "", type: "other", size: "", by: "", at: 0 }));

export type IssueLike = Schemas["WorkspaceIssue"] | (Schemas["IssueRead"] & { project_id?: string });
export function toTask(i: IssueLike, projectId: string, order: number): Task {
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
    archivedAt: i.archived_at ? ms(i.archived_at) : undefined,
    type: i.type,
    parent: i.parent_key ?? null,
  };
}

export const NOTIF_IN: Record<string, NotifType> = {
  assigned: "assign",
  mention: "mention",
  watching: "update",
  approval: "approval",
  checkpoint: "checkpoint",
  finding: "finding",
  decided: "decided",
  limit: "limit",
  stale: "stale",
};
export function toNotif(n: Schemas["NotificationRead"]): Notif {
  return {
    id: n.id,
    type: NOTIF_IN[n.kind] ?? "update",
    by: n.actor_user_id ?? agentId(n.actor_agent),
    task: n.issue_key ?? undefined,
    project: n.project_id,
    thread: n.thread_id ?? undefined,
    run: n.run_id ?? undefined,
    text: n.title,
    snippet: n.excerpt ?? "",
    at: ms(n.created_at),
    read: n.read || n.resolved,
  };
}

export function toActivity(a: Schemas["ActivityItem"]): Activity {
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
  if (a.schedule_hour != null)
    parts.unshift(a.schedule_weekday != null ? `Weekly, ${SCHEDULE_DAYS[a.schedule_weekday]} ${hour(a.schedule_hour)}` : `Daily, ${hour(a.schedule_hour)}`);
  return parts.join(" · ") || "Run by hand";
}
export const toAutomation = (a: Schemas["AutomationRead"]): Automation => ({
  id: a.id,
  project: a.project_id,
  name: a.name,
  agent: AGENT_IN[a.agent] ?? a.agent,
  trigger: triggerLabel(a),
  enabled: a.enabled,
  unattended: a.unattended,
});

export function toKnowledge(f: Schemas["FileRead"], pid: string): KnowledgeFile {
  return { path: f.path, project: pid, content: f.content, version: f.version, by: "", at: ms(f.updated_at) };
}
export function toFile(d: Schemas["DocumentRead"], pid: string): FileItem {
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
export const toAudit = (a: Schemas["AuditEventRead"]): AuditEvent => ({
  id: a.id,
  at: ms(a.created_at),
  by: actor(a.actor_user_id, a.agent),
  action: a.action,
  target: a.target ?? "",
  project: a.project_id ?? undefined,
});
/** An agent as the store has it: the API's definition, with the store's icon and colour for it. */
export function toAgent(a: Schemas["AgentRead"]): Agent {
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

/** A comment inside an issue's log. */
export function logComment(
  e: {
    id: string;
    kind: string;
    body?: string | null;
    author_user_id?: string | null;
    author_agent?: string | null;
    created_at: string;
    reactions?: Record<string, string[]> | null;
  },
  taskId: string,
) {
  return { id: e.id, task: taskId, by: actor(e.author_user_id, e.author_agent), at: ms(e.created_at), text: e.body!, re: e.reactions ?? {} };
}

/** A non-comment entry of an issue's log as an activity line (the drawer's activity tab). */
export function logActivity(
  e: {
    id: string;
    kind: string;
    author_user_id?: string | null;
    author_agent?: string | null;
    created_at: string;
    changes?: Record<string, unknown> | null;
  },
  taskId: string,
): Activity {
  const verb: Record<string, string> = { created: "created", updated: "updated", commented: "commented on", claimed: "started" };
  const extra = Object.entries(e.changes ?? {})
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? `${v[0] ?? "—"} → ${v[1] ?? "—"}` : String(v)}`)
    .join(", ");
  return { id: e.id, task: taskId, by: actor(e.author_user_id, e.author_agent), verb: verb[e.kind] ?? "updated", project: null, at: ms(e.created_at), extra };
}

/** A workspace conversation as a store Thread (summary only — its messages load with the thread). */
export function toThread(c: Schemas["WorkspaceConversation"]): Thread {
  return {
    id: c.thread_id,
    project: c.project_ids[0] ?? null,
    projects: c.project_ids,
    title: c.title,
    by: "",
    agent: "",
    model: c.model ?? "",
    at: ms(c.updated_at),
    messages: [],
  };
}

/** A coding session row as a store CodingSession (its turns/diffs load with the session itself). */
export function toCodingSession(s: Schemas["CodingSessionRead"]): CodingSession {
  return {
    id: s.session_id,
    project: s.project_id,
    task: s.issue_key,
    tool: s.agent,
    status: s.status,
    by: "",
    at: ms(s.updated_at),
    title: s.title,
    pinned: s.pinned,
    archived: s.archived,
    state: s.state,
    branch: s.branch ?? undefined,
    pr: s.pr_url ? { url: s.pr_url, number: s.pr_number ?? 0, state: (s.pr_state ?? "open") as "open" | "merged" | "closed" } : undefined,
    turns: [],
  };
}

export { htmlToMd, mdToHtml };
