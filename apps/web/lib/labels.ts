import type { Schemas } from "@dotrix/api-client";

export const ROLE_LABELS: Record<Schemas["Role"], string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
  guest: "Guest",
};

const AGENT_NAMES: Record<string, string> = {
  "project-manager": "Nova",
  auto: "Nova",
  product: "Lyra",
  architecture: "Orion",
  research: "Vega",
  reviewer: "Juno",
  documentation: "Echo",
  coding: "Coding agent",
};

/** An agent's name from its role ("research") or LangGraph name ("research-agent"). */
export function agentName(agent: string | null | undefined): string {
  const key = agent?.replace(/-agent$/, "") ?? "";
  return AGENT_NAMES[key] ?? AGENT_NAMES[agent ?? ""] ?? (agent ? `${agent} agent` : "An agent");
}
