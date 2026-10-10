// dotrix's part of the seeded workspace: its agents, chat threads (with changes waiting for a
// decision), each project's knowledge (.dotrix/), coding sessions, the audit log, automations;
// and on Gr8r's data, issue types and the agents' notifications and activity.
import { minsAgo } from "../core/utils";
import type {
  Activity,
  Agent,
  AuditEvent,
  Automation,
  CodingSession,
  KnowledgeFile,
  Notif,
  Task,
  Thread,
} from "./types";

type Base = { tasks: Task[]; notifs: Notif[]; activity: Activity[] };

export const AGENTS: Agent[] = [
  { handle: "auto", name: "Nova", role: "Lead", desc: "Plans the work, hands it to the right agent, and brings it together.", icon: "sparkles", c: "#E0A92E", builtIn: true, tools: ["knowledge.read", "board.write", "graph.read", "code.read"] },
  { handle: "product", name: "Lyra", role: "Product", desc: "Requirements, user stories, acceptance criteria.", icon: "target", c: "#3D9E6A", builtIn: true, tools: ["knowledge.write", "board.write"] },
  { handle: "architecture", name: "Orion", role: "Architecture", desc: "Impact of a change, options, decisions (ADRs).", icon: "layers", c: "#3B82C4", builtIn: true, tools: ["knowledge.write", "code.read", "graph.read"] },
  { handle: "research", name: "Vega", role: "Research", desc: "Reads the web and our documents; claims with sources.", icon: "search", c: "#5AA9D6", builtIn: true, tools: ["web.search", "knowledge.read"] },
  { handle: "reviewer", name: "Juno", role: "Review", desc: "Checks work against requirements; read-only.", icon: "shield-check", c: "#D0628B", builtIn: true, customised: true, tools: ["knowledge.read", "code.read"] },
  { handle: "documentation", name: "Echo", role: "Documentation", desc: "Keeps documents current after changes.", icon: "file-text", c: "#8C6FD6", builtIn: true, tools: ["knowledge.write"] },
];
/** Coding tools: assignable like people, they open pull requests. */
export const CODING_TOOLS = [
  { id: "agent:claude-code", name: "Claude Code", c: "#C0612B" },
  { id: "agent:codex", name: "Codex", c: "#1D1C1A" },
];

const diffNav = ` # Navigation

 The site has five top-level sections.
-Products, Solutions, Pricing, Resources, Company.
+Product, Pricing, Customers, Resources, Company.
+
+## Mobile
+The drawer opens from the left and keeps the search field at the top.`;

const THREADS: Thread[] = [
  {
    id: "th1",
    project: "p1",
    title: "What's left before dev handoff?",
    by: "m1",
    agent: "auto",
    model: "Gemini 3.8 Flash",
    at: minsAgo(25),
    messages: [
      { id: "cm1", role: "user", by: "m1", at: minsAgo(32), text: "What's left before the dev handoff, and is anything at risk?" },
      {
        id: "cm2",
        role: "agent",
        by: "auto",
        at: minsAgo(30),
        activity: ["Read roadmap.md", "Read requirements/navigation.md", "Listed the board", "Asked Juno to review"],
        tokens: 18420,
        text: "Three things stand between you and **Dev handoff** (in 14 days):\n\n1. **WEB-109 Create homepage wireframes** is in review: the annotations subtask is still open.\n2. **WEB-112 Finalize navigation** is due today and the mega-menu content isn't in yet.\n3. **WEB-127 Design mobile onboarding** is a day overdue; the permission prompts wait on legal.\n\nThe navigation requirements still describe the old menu, so I've proposed an update below, and an issue to track the legal review.",
        changes: [
          { id: "pc1", kind: "write_file", title: "requirements/navigation.md", diff: diffNav, status: "pending" },
          {
            id: "pc2",
            kind: "create_issue",
            title: "Legal review of permission prompts",
            fields: { Type: "Task", Priority: "High", Assignee: "Emma Wilson", Due: "In 3 days" },
            status: "pending",
          },
        ],
      },
    ],
  },
  {
    id: "th2",
    project: "p2",
    title: "Offline sync options",
    by: "m3",
    agent: "architecture",
    model: "Gemini 3.8 Flash",
    at: minsAgo(300),
    messages: [
      { id: "cm3", role: "user", by: "m3", at: minsAgo(310), text: "@architecture what are our options for offline sync on mobile?" },
      {
        id: "cm4",
        role: "agent",
        by: "architecture",
        at: minsAgo(305),
        activity: ["Read architecture/overview.md", "Searched the code for 'sync'", "Started a plan"],
        tokens: 31200,
        text: "Before I go deep, here's the plan. Change it or continue.",
        changes: [
          {
            id: "pc3",
            kind: "checkpoint",
            title: "Plan: offline sync",
            plan: ["Map what the app reads and writes offline", "Compare CRDTs, last-write-wins, and a server queue", "Recommend one, with an ADR draft"],
            status: "pending",
          },
        ],
      },
    ],
  },
  {
    id: "th3",
    project: "p4",
    title: "Launch risks this week",
    by: "m1",
    agent: "auto",
    model: "Gemini 3.8 Flash",
    at: minsAgo(1500),
    messages: [
      { id: "cm5", role: "user", by: "m1", at: minsAgo(1510), text: "Summarise the launch risks for this week." },
      {
        id: "cm6",
        role: "agent",
        by: "auto",
        at: minsAgo(1505),
        activity: ["Read current-state.md", "Listed the board"],
        tokens: 9300,
        text: "**Product Launch is at risk.** Three issues due this week haven't started (pricing page, sales docs, release notes), and the go / no-go is in 11 days. Support training moved to Monday.\n\nNothing needs a decision from you yet.",
      },
    ],
  },
  {
    id: "th4",
    project: null,
    projects: ["p1", "p2", "p4"],
    title: "Weekly summary of all projects",
    by: "m1",
    agent: "auto",
    model: "Gemini 3.8 Flash",
    at: minsAgo(4300),
    messages: [
      { id: "cm7", role: "user", by: "m1", at: minsAgo(4320), text: "Summarise all my projects for the week." },
      {
        id: "cm8",
        role: "agent",
        by: "auto",
        at: minsAgo(4310),
        activity: ["Read 3 projects' current state", "Listed 3 boards"],
        tokens: 22100,
        text: "- **Website Redesign** 22% done, on track for dev handoff.\n- **Mobile App** beta build in 9 days; offline sync is the long pole.\n- **Product Launch** at risk: pricing and sales docs haven't started.",
      },
    ],
  },
  {
    id: "th5",
    project: "p1",
    title: "What blocks the dev handoff",
    by: "m1",
    agent: "auto",
    model: "Claude Sonnet 5.5",
    at: minsAgo(3),
    messages: [
      { id: "cm9", role: "user", by: "m1", at: minsAgo(4), text: "What still blocks the dev handoff?" },
      {
        id: "cm10",
        role: "agent",
        by: "auto",
        at: minsAgo(3),
        activity: ["Read current-state.md", "Listed the board"],
        tokens: 6400,
        text: "I'd read the board and the current state when the model's limit was reached.",
        limit: { provider: "Anthropic", resetsAt: Date.now() + 4 * 60_000 },
      },
    ],
  },
];

const md = (title: string, body: string) => `# ${title}\n\n${body}\n`;
const KNOWLEDGE: KnowledgeFile[] = [
  { path: "project.md", project: "p1", version: 3, by: "m2", at: minsAgo(9000), content: md("Website Redesign", "Rebuild dotrix.app with a clearer information architecture, a responsive component library, and a faster CMS-driven blog.\n\n## Goals\n- Visitors find pricing in one click\n- Pages load under 1.5 s on 4G\n- Marketing publishes without engineering") },
  { path: "current-state.md", project: "p1", version: 7, by: "documentation", at: minsAgo(400), content: md("Current state", "Wireframes are in review; navigation is due today. Dev handoff in 14 days.\n\n**Blocked:** mobile onboarding permission prompts (legal).") },
  { path: "roadmap.md", project: "p1", version: 4, by: "m1", at: minsAgo(3000), content: md("Roadmap", "| Milestone | Date |\n| --- | --- |\n| Wireframes signed off | in 2 days |\n| Dev handoff | in 14 days |\n| Public launch | in 24 days |") },
  { path: "requirements/navigation.md", project: "p1", version: 2, by: "product", at: minsAgo(8000), content: md("Navigation", "The site has five top-level sections.\nProducts, Solutions, Pricing, Resources, Company.") },
  { path: "requirements/homepage.md", project: "p1", version: 1, by: "m2", at: minsAgo(12000), content: md("Homepage", "## Acceptance criteria\n- Hero states the value proposition in one sentence\n- Customer logos under the hero\n- Feature overview links to product pages") },
  { path: "decisions/0001-headless-cms.md", project: "p1", version: 1, by: "architecture", at: minsAgo(20000), content: md("ADR 0001: Headless CMS", "**Status:** accepted\n\nWe move the blog to a headless CMS so marketing publishes without a deploy.\n\nAffected modules: blog, build") },
  { path: "research/2026-09-cms-options.md", project: "p1", version: 1, by: "research", at: minsAgo(21000), content: md("CMS options", "Compared three headless CMSs on price, editor experience, and image handling. [S1] [S2]") },
  { path: "agent-rules/base.md", project: "p1", version: 1, by: "m1", at: minsAgo(30000), content: md("Rules for every agent", "- Write in plain English.\n- Link issues by key.") },
  { path: "project.md", project: "p2", version: 2, by: "m3", at: minsAgo(15000), content: md("Mobile App", "Native iOS and Android client for field teams with offline sync, push notifications, and biometric sign-in.") },
  { path: "architecture/overview.md", project: "p2", version: 3, by: "architecture", at: minsAgo(9000), content: md("Architecture overview", "React Native app, a sync service, and the existing REST API.") },
  { path: "project.md", project: "p4", version: 1, by: "m1", at: minsAgo(30000), content: md("Product Launch", "Coordinate the Workflows 2.0 launch: pricing, docs, press, and sales enablement across teams.") },
];

const CODING: CodingSession[] = [
  {
    id: "cs1",
    project: "p1",
    task: "t18",
    tool: "claude-code",
    status: "pr_opened",
    by: "m3",
    at: minsAgo(2900),
    branch: "dotrix/web-154-fix-broken-anchor-links",
    pr: { number: 42, state: "merged", url: "https://github.com/dotrix/site/pull/42" },
    turns: [{ at: minsAgo(2900), ask: "Fix the anchor links on the pricing page.", summary: "Fixed 4 anchors and added a test for heading ids.", events: ["Read pricing.tsx", "Edited 2 files", "Ran the tests: 48 passed"] }],
  },
  {
    id: "cs2",
    project: "p1",
    task: "t13",
    tool: "claude-code",
    status: "awaiting_approval",
    by: "m3",
    at: minsAgo(45),
    turns: [{ at: minsAgo(45), ask: "Build the hero component from the wireframes.", events: [] }],
  },
  {
    id: "cs3",
    project: "p2",
    task: "t24",
    tool: "codex",
    status: "running",
    by: "m3",
    at: minsAgo(12),
    branch: "dotrix/mob-118-biometric-sign-in",
    turns: [{ at: minsAgo(12), ask: "Add the Android fallback to passcode.", events: ["Read auth/biometric.ts", "Editing auth/biometric.ts"] }],
  },
];

const AUDIT: AuditEvent[] = [
  { id: "au1", at: minsAgo(25), by: "auto", action: "agent.run", target: "What's left before dev handoff?", project: "p1" },
  { id: "au2", at: minsAgo(400), by: "m1", action: "approval.approved", target: "current-state.md", project: "p1" },
  { id: "au3", at: minsAgo(2900), by: "m3", action: "coding.started", target: "WEB-154", project: "p1" },
  { id: "au4", at: minsAgo(6000), by: "m1", action: "workspace_rules.saved", target: "base" },
  { id: "au5", at: minsAgo(9000), by: "m2", action: "project.access_changed", target: "Customer Portal", project: "p6" },
  { id: "au6", at: minsAgo(12000), by: "m1", action: "invite.sent", target: "diego@freelance.io" },
];

const AUTOMATIONS: Automation[] = [
  { id: "am1", project: "p1", name: "Keep documents current", agent: "documentation", trigger: "After approved changes", enabled: true, last: minsAgo(400) },
  { id: "am2", project: "p1", name: "Flag stale documents", agent: "documentation", trigger: "Weekly, Monday 08:00", enabled: true, last: minsAgo(4000) },
  { id: "am3", project: "p2", name: "Triage new bugs", agent: "auto", trigger: "When an issue is created", enabled: false },
];

export function seedDotrix(base: Base) {
  // Issue types on Gr8r's tasks: an epic per big piece, stories under it.
  const byId = new Map(base.tasks.map((t) => [t.id, t]));
  for (const [id, type] of [
    ["t3", "story"],
    ["t4", "story"],
    ["t5", "story"],
    ["t9", "story"],
    ["t19", "story"],
    ["t20", "story"],
    ["t21", "story"],
    ["t36", "spike"],
  ] as const) {
    const t = byId.get(id);
    if (t) t.type = type;
  }
  // Agents' items in the inbox: changes waiting, a plan to steer, a finding.
  const notifs: Notif[] = [
    { id: "na1", type: "approval", by: "auto", project: "p1", thread: "th1", text: "wants to change", snippet: "requirements/navigation.md, and 1 more change", at: minsAgo(30), read: false },
    { id: "na2", type: "checkpoint", by: "architecture", project: "p2", thread: "th2", text: "shared a plan for", snippet: "Offline sync: map, compare, recommend", at: minsAgo(305), read: false },
    { id: "na3", type: "finding", by: "reviewer", task: "t3", text: "found an issue in", snippet: "Mobile layout has no acceptance criteria for the logo strip", at: minsAgo(700), read: true },
    { id: "na5", type: "limit", by: "auto", project: "p1", thread: "th5", run: "run-th5", text: "stopped at its model's limit in", snippet: "Anthropic: rate limit reached, resets in about 4 minutes", at: minsAgo(3), read: false },
    { id: "na4", type: "approval", by: "agent:claude-code", project: "p1", task: "t13", text: "is waiting to start coding", snippet: "WEB-139 Build hero component", at: minsAgo(45), read: false },
  ];
  const activity: Activity[] = [
    { id: "aa1", by: "auto", verb: "answered", task: null, project: "p1", at: minsAgo(30), extra: "What's left before dev handoff?" },
    { id: "aa2", by: "documentation", verb: "updated", task: null, project: "p1", at: minsAgo(400), extra: "current-state.md" },
    { id: "aa3", by: "agent:claude-code", verb: "opened PR #42 for", task: "t18", project: "p1", at: minsAgo(2880), extra: "" },
  ];
  return {
    agents: AGENTS,
    threads: THREADS,
    knowledge: KNOWLEDGE,
    coding: CODING,
    audit: AUDIT,
    automations: AUTOMATIONS,
    notifs: [...notifs, ...base.notifs],
    activity: [...activity, ...base.activity].sort((a, b) => b.at - a.at),
  };
}
