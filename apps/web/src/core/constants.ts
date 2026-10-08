// Gr8r's vocabulary (gr8r-studio/src/core/constants.js), with dotrix's additions marked.
export type StatusId = "backlog" | "todo" | "progress" | "blocked" | "review" | "done";
export type PriorityId = "urgent" | "high" | "medium" | "low" | "none";

// dotrix adds Blocked (agents and people flag it); Gr8r's five otherwise.
export const STATUSES: { id: StatusId; name: string }[] = [
  { id: "backlog", name: "Backlog" },
  { id: "todo", name: "To Do" },
  { id: "progress", name: "In Progress" },
  { id: "blocked", name: "Blocked" },
  { id: "review", name: "Review" },
  { id: "done", name: "Done" },
];
export const ST = Object.fromEntries(STATUSES.map((s) => [s.id, s])) as Record<StatusId, { id: StatusId; name: string }>;
export const PRIOS: { id: PriorityId; name: string; w: number }[] = [
  { id: "urgent", name: "Urgent", w: 4 },
  { id: "high", name: "High", w: 3 },
  { id: "medium", name: "Medium", w: 2 },
  { id: "low", name: "Low", w: 1 },
  { id: "none", name: "No priority", w: 0 },
];
export const PR = Object.fromEntries(PRIOS.map((p) => [p.id, p])) as Record<PriorityId, { id: PriorityId; name: string; w: number }>;
export const LABELS = [
  { id: "design", name: "Design", c: "var(--violet)" },
  { id: "frontend", name: "Frontend", c: "var(--blue)" },
  { id: "backend", name: "Backend", c: "var(--teal)" },
  { id: "research", name: "Research", c: "var(--amber)" },
  { id: "content", name: "Content", c: "var(--rose)" },
  { id: "bug", name: "Bug", c: "var(--red)" },
  { id: "qa", name: "QA", c: "var(--green)" },
  { id: "growth", name: "Growth", c: "var(--orange)" },
];
export const LB = Object.fromEntries(LABELS.map((l) => [l.id, l])) as Record<string, (typeof LABELS)[number]>;
export type ProjectStatusId = "planning" | "active" | "risk" | "hold" | "complete";
export const PSTAT: Record<ProjectStatusId, { name: string; c: string }> = {
  planning: { name: "Planning", c: "var(--gray)" },
  active: { name: "In Progress", c: "var(--blue)" },
  risk: { name: "At Risk", c: "var(--red)" },
  hold: { name: "On Hold", c: "var(--amber)" },
  complete: { name: "Completed", c: "var(--green)" },
};
export const PCOLORS: Record<string, string> = {
  indigo: "#5A67D8",
  blue: "#3B82C4",
  violet: "#8662C9",
  teal: "#23918A",
  rose: "#C54B78",
  amber: "#C48A1E",
  green: "#3D8E5F",
  slate: "#6B7280",
};
export const PICONS = [
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
];
export const ROLES = ["Owner", "Admin", "Member", "Guest"] as const;
export type Role = (typeof ROLES)[number];
export const TEAMS_SEED = [
  { id: "design", name: "Design", icon: "palette", c: "#8662C9", desc: "Product design, brand, and research" },
  { id: "eng", name: "Engineering", icon: "code", c: "#3B82C4", desc: "Web, mobile, and platform engineering" },
  { id: "mkt", name: "Marketing", icon: "megaphone", c: "#C54B78", desc: "Campaigns, content, and growth" },
  { id: "product", name: "Product", icon: "target", c: "#C48A1E", desc: "Roadmap, planning, and QA" },
];

/* dotrix: issue types (Gr8r's tasks are all "task") */
export type IssueType = "epic" | "story" | "task" | "bug" | "spike" | "sub-task";
export const TYPES: { id: IssueType; name: string; icon: string; c: string }[] = [
  { id: "epic", name: "Epic", icon: "zap", c: "var(--violet)" },
  { id: "story", name: "Story", icon: "bookmark", c: "var(--green)" },
  { id: "task", name: "Task", icon: "square-check", c: "var(--blue)" },
  { id: "bug", name: "Bug", icon: "bug", c: "var(--red)" },
  { id: "spike", name: "Spike", icon: "flask-conical", c: "var(--amber)" },
  { id: "sub-task", name: "Sub-task", icon: "corner-down-right", c: "var(--gray)" },
];
export const TY = Object.fromEntries(TYPES.map((t) => [t.id, t])) as Record<IssueType, (typeof TYPES)[number]>;
