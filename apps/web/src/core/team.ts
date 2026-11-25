// Built-in Dotrix agent identities shared across live workspaces and onboarding.
import type { Agent } from "../data/types";

export const AGENTS: Agent[] = [
  {
    handle: "auto",
    name: "Nova",
    role: "Lead",
    desc: "Plans the work, hands it to the right agent, and brings it together.",
    icon: "sparkles",
    c: "#E0A92E",
    builtIn: true,
    tools: ["knowledge.read", "board.write", "graph.read", "code.read"],
  },
  {
    handle: "product",
    name: "Lyra",
    role: "Product",
    desc: "Requirements, user stories, acceptance criteria.",
    icon: "target",
    c: "#3D9E6A",
    builtIn: true,
    tools: ["knowledge.write", "board.write"],
  },
  {
    handle: "architecture",
    name: "Orion",
    role: "Architecture",
    desc: "Impact of a change, options, decisions (ADRs).",
    icon: "layers",
    c: "#3B82C4",
    builtIn: true,
    tools: ["knowledge.write", "code.read", "graph.read"],
  },
  {
    handle: "research",
    name: "Vega",
    role: "Research",
    desc: "Reads the web and our documents; claims with sources.",
    icon: "search",
    c: "#5AA9D6",
    builtIn: true,
    tools: ["web.search", "knowledge.read"],
  },
  {
    handle: "reviewer",
    name: "Juno",
    role: "Review",
    desc: "Checks work against requirements; read-only.",
    icon: "shield-check",
    c: "#D0628B",
    builtIn: true,
    tools: ["knowledge.read", "code.read"],
  },
  {
    handle: "documentation",
    name: "Echo",
    role: "Documentation",
    desc: "Keeps documents current after changes.",
    icon: "file-text",
    c: "#8C6FD6",
    builtIn: true,
    tools: ["knowledge.write"],
  },
];

/** Kai, the coding agent: assignable like people, it opens pull requests. Whatever engine codes for it
 * underneath, people see Kai, so every engine's id answers to Kai. */
export const CODING_AGENT = { id: "agent:coding-agent", name: "Kai", c: "#3D6B8C" };
export const CODING_TOOLS = [CODING_AGENT, ...["claude-code", "codex", "opencode", "fx"].map((engine) => ({ ...CODING_AGENT, id: `agent:${engine}` }))];
