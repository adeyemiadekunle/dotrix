// Domain types shared by web, desktop, and the API client. Mirrors the PRD.

export const ISSUE_TYPES = ["epic", "story", "task", "bug", "spike", "sub-task"] as const;
export type IssueType = (typeof ISSUE_TYPES)[number];

export const ISSUE_STATUSES = ["todo", "in_progress", "blocked", "review", "done"] as const;
export type IssueStatus = (typeof ISSUE_STATUSES)[number];

export const PRIORITIES = ["low", "medium", "high", "urgent"] as const;
export type Priority = (typeof PRIORITIES)[number];

export const ROLES = ["owner", "admin", "member", "guest"] as const;
export type Role = (typeof ROLES)[number];

export const WORKSPACE_KINDS = ["personal", "team", "business"] as const;
export type WorkspaceKind = (typeof WORKSPACE_KINDS)[number];

export const AGENTS = [
  "project-manager",
  "product",
  "architecture",
  "research",
  "reviewer",
  "documentation",
  "coding",
] as const;
export type AgentName = (typeof AGENTS)[number];

export interface Issue {
  key: string; // e.g. "KUN-42"
  type: IssueType;
  title: string;
  status: IssueStatus;
  priority: Priority;
  assignee?: string;
  reporter?: string;
  parent?: string;
  sprint?: string;
  due?: string;
  dependsOn: string[];
  labels: string[];
}
