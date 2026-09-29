import type { Schemas } from "@pmagent/api-client";

export const ROLE_LABELS: Record<Schemas["Role"], string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
  guest: "Guest",
};

export const WORKSPACE_KIND_LABELS: Record<Schemas["WorkspaceKind"], string> = {
  personal: "Personal",
  team: "Team",
  business: "Business",
};

export const PROJECT_SOURCE_LABELS: Record<Schemas["ProjectSource"], string> = {
  new_repo: "New repo",
  existing_repo: "Existing repo",
  docs_only: "Docs only",
};

const AGENT_NAMES: Record<string, string> = {
  "project-manager": "PM agent",
  product: "Product agent",
  architecture: "Architecture agent",
  research: "Research agent",
  reviewer: "Reviewer agent",
  documentation: "Documentation agent",
  coding: "Coding agent",
};

/** An agent's name from its role ("research") or LangGraph name ("research-agent"). */
export function agentName(agent: string | null | undefined): string {
  const key = agent?.replace(/-agent$/, "") ?? "";
  return AGENT_NAMES[key] ?? AGENT_NAMES[agent ?? ""] ?? (agent ? `${agent} agent` : "An agent");
}

/** Mirrors the backend's permission matrix for showing or hiding controls; the API still decides. */
export function canManageProjects(role: Schemas["Role"] | undefined): boolean {
  return role === "owner" || role === "admin";
}

export type Permission = Schemas["Permission"];

/** What you can do in a workspace: your role's permissions plus what the workspace grants
 * members (the API sends them with the workspace). For showing controls; the API still decides. */
export function can(workspace: { permissions?: Permission[] } | undefined, permission: Permission): boolean {
  return Boolean(workspace?.permissions?.includes(permission));
}

/** What a workspace can let members do beyond chatting, brainstorming, and working the board. */
export const MEMBER_GRANTS: { permission: Permission; label: string; description: string }[] = [
  {
    permission: "knowledge:write",
    label: "Edit documents",
    description: "Change the project's documents directly in Knowledge (never the agent rules).",
  },
  {
    permission: "agents:approve",
    label: "Approve agent changes",
    description: "Approve or reject the changes agents propose, including ones they asked for themselves.",
  },
  {
    permission: "agents:code",
    label: "Assign the coding agent",
    description: "Hand issues to the coding agent.",
  },
  {
    permission: "agents:choose_model",
    label: "Choose the model",
    description: "Start conversations on a model other than the project's (a bigger model costs more).",
  },
];

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts.at(-1)?.[0] ?? "") : "")).toUpperCase() || "?";
}

export function withArticle(word: string): string {
  return `${/^[aeiou]/i.test(word) ? "an" : "a"} ${word}`;
}

/** Suggest a key from the name: initials of the words, or the first letters of one word. */
export function suggestKey(name: string): string {
  const words = name.toUpperCase().match(/[A-Z0-9]+/g) ?? [];
  const key = words.length > 1 ? words.map((w) => w[0]).join("") : (words[0] ?? "").slice(0, 4);
  return key.replace(/^[0-9]+/, "").slice(0, 10);
}
