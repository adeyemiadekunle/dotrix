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

/** Mirrors the backend's permission matrix for showing or hiding controls; the API still decides. */
export function canManageProjects(role: Schemas["Role"] | undefined): boolean {
  return role === "owner" || role === "admin";
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts.at(-1)?.[0] ?? "") : "")).toUpperCase() || "?";
}

export function withArticle(word: string): string {
  return `${/^[aeiou]/i.test(word) ? "an" : "a"} ${word}`;
}
