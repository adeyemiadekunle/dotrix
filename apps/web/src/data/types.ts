// The seeded workspace's shape (Gr8r's data, plus dotrix's agents, chat, knowledge, coding).
// When the API is wired, these become views over the API's schemas.
import type { IssueType, PriorityId, ProjectStatusId, Role, StatusId } from "../core/constants";

export interface Member {
  id: string;
  name: string;
  email: string;
  role: Role;
  team: string;
  title: string;
  c: string;
  status: "active" | "invited" | "deactivated";
  last: number | null; // minutes since last active; null: never
  tz: string;
}
export interface Milestone {
  name: string;
  date: string;
  done?: boolean;
}
export interface Project {
  id: string;
  key: string;
  name: string;
  icon: string;
  color: string;
  status: ProjectStatusId;
  team: string;
  lead: string;
  due: string;
  start: string;
  fav: boolean;
  members: string[];
  desc: string;
  milestones: Milestone[];
  last: number;
  private?: boolean;
  archived?: boolean;
  /** dotrix: the connected repo, and the agents' model */
  repo?: string;
  model?: string;
}
export interface Subtask {
  id: string;
  title: string;
  done: boolean;
  due?: string | null;
  assignee?: string | null;
  desc?: string;
}
export interface Attachment {
  id: string;
  name: string;
  type: string;
  size: string;
  by: string;
  at: number;
}
export interface Task {
  id: string;
  key: string;
  project: string;
  title: string;
  status: StatusId;
  /** a person (m1…), or a coding agent (agent:claude-code, agent:codex) */
  assignee: string | null;
  priority: PriorityId;
  due: string | null;
  start: string | null;
  labels: string[];
  subtasks: Subtask[];
  attachments: Attachment[];
  deps: string[];
  desc: string;
  estimate: string | null;
  created: number;
  updated: number;
  order: number;
  fav: boolean;
  recur: string | null;
  completedAt?: number;
  archived?: boolean;
  len?: number;
  est?: string;
  age?: number;
  upd?: number;
  /** dotrix */
  type: IssueType;
  parent?: string | null;
}
export interface Comment {
  id: string;
  task: string;
  by: string;
  at: number;
  text: string;
  re: Record<string, string[]>;
}
export interface Activity {
  id: string;
  /** a member id, or an agent handle (agent:research) */
  by: string;
  verb: string;
  task: string | null;
  project: string | null;
  at: number;
  extra: string;
}
export type NotifType = "mention" | "assign" | "comment" | "update" | "approval" | "checkpoint" | "finding" | "decided";
export interface Notif {
  id: string;
  type: NotifType;
  by: string | null;
  task?: string;
  project?: string;
  /** dotrix: the chat thread an agent item belongs to */
  thread?: string;
  text: string;
  snippet: string;
  at: number;
  read: boolean;
}
export interface FileItem {
  id: string;
  project: string;
  name: string;
  type: string;
  size: string;
  by: string;
  at: number;
  task?: string;
  /** dotrix: converted to Markdown into the project's knowledge */
  converted?: "ready" | "converting" | "failed";
}
export interface CalEvent {
  id: string;
  title: string;
  date: string;
  time: string;
  project: string;
}
export interface SavedView {
  id: string;
  project: string;
  name: string;
  type: string;
  filters: Filter[];
}
export interface Filter {
  f: string;
  op: "is" | "not";
  v: string[];
}
export interface Team {
  id: string;
  name: string;
  icon: string;
  c: string;
  desc: string;
}
export interface Workspace {
  id: string;
  name: string;
  c: string;
  plan: string;
  brand?: boolean;
  /** a real workspace's address (/w/{slug}); the demo has none */
  slug?: string;
  /** dotrix: personal workspaces never invite */
  kind?: "personal" | "organization";
}

/* ---------- dotrix ---------- */

export interface Agent {
  handle: string; // "auto", "product", ...
  name: string;
  desc: string;
  icon: string;
  c: string;
  builtIn: boolean;
  customised?: boolean;
  tools: string[];
  model?: string;
}
/** A change an agent wants to make, waiting for a person (an approval). */
export interface ProposedChange {
  id: string;
  kind: "create_issue" | "update_issue" | "comment" | "write_file" | "checkpoint";
  title: string;
  /** a document's diff (unified, lines starting +/-/space) */
  diff?: string;
  /** an issue's fields */
  fields?: Record<string, string>;
  /** a checkpoint's plan */
  plan?: string[];
  status: "pending" | "approved" | "rejected";
  reason?: string;
  decidedBy?: string;
}
export interface ChatMessage {
  id: string;
  role: "user" | "agent";
  by: string; // member id, or agent handle
  at: number;
  text: string; // Markdown
  /** what the agent did while answering ("Read roadmap.md") */
  activity?: string[];
  changes?: ProposedChange[];
  tokens?: number;
}
export interface Thread {
  id: string;
  project: string | null; // null: across projects
  projects?: string[];
  title: string;
  by: string;
  agent: string; // the agent picked (auto, product, …)
  model: string;
  at: number;
  messages: ChatMessage[];
}
export interface KnowledgeFile {
  path: string; // "requirements/checkout.md"
  project: string;
  content: string;
  version: number;
  by: string; // a member, or an agent handle
  at: number;
}
export interface CodingSession {
  id: string;
  project: string;
  task: string;
  tool: "claude-code" | "codex";
  status: "awaiting_approval" | "queued" | "running" | "pr_opened" | "no_changes" | "failed" | "stopped" | "rejected";
  by: string;
  at: number;
  branch?: string;
  pr?: { number: number; state: "open" | "merged" | "closed"; url: string };
  turns: { at: number; ask: string; summary?: string; events: string[] }[];
}
export interface AuditEvent {
  id: string;
  at: number;
  by: string;
  action: string;
  target: string;
  project?: string;
}
export interface Automation {
  id: string;
  project: string;
  name: string;
  agent: string;
  trigger: string;
  enabled: boolean;
  last?: number;
}

export interface Data {
  ws: Workspace & { url: string };
  workspaces: Workspace[];
  me: string;
  members: Member[];
  projects: Project[];
  tasks: Task[];
  comments: Comment[];
  activity: Activity[];
  notifs: Notif[];
  files: FileItem[];
  events: CalEvent[];
  projOrder: string[];
  savedViews: SavedView[];
  recentSearches: string[];
  sessions: { id: string; dev: string; loc: string; at: string; cur?: boolean }[];
  invoices: { id: string; date: string; amt: string; st: string }[];
  tfa: boolean;
  notifPrefs: Record<string, boolean>;
  teams?: Team[];
  /* dotrix */
  agents: Agent[];
  threads: Thread[];
  knowledge: KnowledgeFile[];
  coding: CodingSession[];
  audit: AuditEvent[];
  automations: Automation[];
}
