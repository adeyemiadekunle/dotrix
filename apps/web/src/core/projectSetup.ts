import type { Schemas } from "@/lib/api";

export const PROJECT_STARTS = [
  { id: "idea", label: "Explore an idea", icon: "sparkles", description: "Clarify a working idea with Nova. No repository needed.", source: "docs_only" },
  { id: "new", label: "Start a new codebase", icon: "code", description: "Define the goal, then prepare a repository and a first task.", source: "new_repo" },
  {
    id: "existing",
    label: "Connect an existing repository",
    icon: "github",
    description: "Bring a GitHub project into Dotrix and understand it.",
    source: "existing_repo",
  },
] as const satisfies readonly { id: string; label: string; icon: string; description: string; source: Schemas["ProjectSource"] }[];
export type ProjectStart = (typeof PROJECT_STARTS)[number]["id"];
export const readProjectStart = (value: string | null): ProjectStart | null => PROJECT_STARTS.find((item) => item.id === value)?.id ?? null;
export const projectStart = (source: Schemas["ProjectSource"]): ProjectStart => PROJECT_STARTS.find((item) => item.source === source)!.id;

// These are editable discussion starters. Project names and private goals stay in project context, out of the URL.
const STARTERS: Record<ProjectStart, string> = {
  idea: "Help me explore this project idea. Start by clarifying the problem, intended users, constraints and uncertainties. Ask focused questions before proposing scope. Involve specialists only when their expertise is useful. Do not implement anything yet.",
  new: "Help me plan this new codebase from the saved project goal. Clarify users, constraints, success criteria and the smallest useful first milestone before proposing scope or architecture. Involve specialists only when needed. Do not start coding yet.",
  existing:
    "Help me understand this existing project and decide the next useful step. Clarify my goals and distinguish repository evidence from assumptions and missing information. Involve specialists only when useful. Do not claim the repository is fully understood or change code yet.",
};
export function projectDiscussionHref(slug: string, key: string, start: ProjectStart): string {
  return `/w/${slug}/chat?${new URLSearchParams({ project: key, q: STARTERS[start] })}`;
}

export function projectImplementationHref(slug: string, key: string): string {
  return `/w/${slug}/chat?${new URLSearchParams({
    project: key,
    mode: "plan",
    q: "Plan the first useful implementation from this project's saved goal and knowledge. Clarify scope and acceptance criteria, save an agreed plan and propose a small initial task. Do not start Kai or change code until I explicitly request implementation in Build mode. Keep checks, independent review and my merge decision explicit.",
  })}`;
}
