# PRD: pmagent, the AI project team for any project

Sep 26, 2026 · @Adeyemi Adekunle

## Summary

pmagent is a standalone product: an AI project team that plans, researches, reviews, documents, and builds any project, tracked on a Jira-style board. Anyone can sign up with a personal, team, or business account, start a new repo or connect an existing one, bring in their docs, and get a Project Manager agent backed by specialists and a coding agent.

**Problem.** AI coding tools write code fast, but nobody keeps the project coherent. Requirements live in scattered docs, decisions are forgotten, coding agents remember nothing between sessions, and Jira-class tools were built for humans, not agents. As projects grow, teams hit **AI project drift**: agents guess instead of knowing, and the plan, the decisions, and the code fall out of sync.

**Solution.** One structured **source of truth** per project, stored on the pmagent platform and never pushed to the code repo, plus a team of agents that works around it:

- A **Project Manager agent** you talk to, which coordinates everything.
- Five **thinking agents** (Product, Architecture, Research, Reviewer, Documentation) that never write code.
- A **coding agent** that builds tasks on a branch and opens a pull request, only when instructed. Teams can also plug in Claude Code or Codex through the same structured files.
- A **Jira-style board** with projects, epics, stories, tasks, bugs, sprints, and backlog.
- **Accounts and workspaces** for individuals, teams, and businesses, with roles that decide who can approve what.

Nothing changes without explicit instruction and approval (Chat Mode vs Action Mode).

**Origin.** The design comes from running Kunemi/Kumove, a large logistics platform, which becomes the first reference customer. Kunemi examples appear throughout as illustrations; nothing in the product is Kunemi-specific.

## Goals, non-goals, and success metrics

**Goals**

1. **Any project, any starting point.** Start a new repo, connect an existing one, or start from docs alone; software or not.
2. **Prevent AI project drift.** Every "why" is answered from a logged decision (ADR), never a guess.
3. **One source of truth, on the platform.** Requirements, architecture, decisions, research, progress, and issues are structured files in `.pmagent/`, kept on the platform with full version history. Claude Code, Codex, and the CLI read a local, git-excluded mirror. The code repo holds code only.
4. **A complete team.** Planning, research, review, documentation, and coding, coordinated by one PM agent.
5. **Jira-style tracking** that humans and agents both use: issue types, epics, sprints, board, backlog.
6. **Nothing changes without permission.** Chat Mode by default; Action Mode only on instruction, with approvals governed by account roles.
7. **Accounts for individuals, teams, and businesses**, with workspaces, roles, invites, and billing.

**Non-goals (v1)**

- Replacing the code host. Repos stay on GitHub or GitLab; pmagent works through branches and pull requests.
- The coding agent never merges to the main branch or deploys; humans merge.
- No custom workflow editor, time tracking, or portfolio reporting in v1.
- No on-premise deployment in v1 (business plan roadmap item).

**Success metrics**

| Metric | Target | How measured |
| --- | --- | --- |
| New workspace reaches first briefing | < 10 min, ≥ 70% of sign-ups | Onboarding funnel |
| Weekly active projects retained at 8 weeks | ≥ 40% | Product analytics |
| "Why" questions answered from an ADR | ≥ 95% | Sampled answers cite an ADR |
| Coding-agent PRs merged without major rework | ≥ 60% | PR outcome after Reviewer pass |
| Writes made without instruction and approval | 0 | Audit log |
| Free-to-paid conversion (team or business) | ≥ 5% | Billing data |

## Target users and personas

Three account types map to three customer segments; within a team or business, people take different roles.

| Persona | Account | Who they are | What they need |
| --- | --- | --- | --- |
| Solo founder / indie builder | Personal | Builds one or a few products, often with AI coding tools (e.g. the Kunemi/Kumove founder) | Briefings, feature thinking, a coding agent, full control of approvals |
| Startup team lead | Team | 2–20 people, shared repos, moving fast | Shared board, roles, invites, sprints, review queue |
| Engineering or product manager at a company | Business | Several teams and many projects, compliance needs | SSO, admin controls, audit log, data retention, usage limits |
| Contributor / developer | Team or Business member | Picks up and reviews work | Clear issues, PR hand-off, notifications |
| Stakeholder / viewer | Any, as guest | Needs status, not detail | Read-only board and briefings |
| External coding tool | Connected (Claude Code, Codex) | Remembers nothing between sessions | Structured files and one issue at a time |

## System overview

pmagent has four layers: clients people use, a hosted platform for accounts, the board, and each project's `.pmagent/` source of truth, an agent team per project, and the customer's code host, which holds code only.

&#91;embedded content: platform overview · clients, platform layer, agent team, project repo, connectors\]

The platform handles who you are, which workspaces and projects you can see, and who may approve what, and it stores every project's `.pmagent/`. That folder is never pushed to GitHub or GitLab; tools like Claude Code and Codex read a synced, git-excluded local copy. The coding agent works only on a branch and opens a pull request containing code only; humans merge.

**Default delegation for a new feature** (for example "I want to add scheduled delivery")

1. **Product agent** defines the feature: why, who, user stories, business rules, edge cases, acceptance criteria.
2. **Architecture agent** identifies technical impact: which modules and entities change.
3. **Research agent** finds relevant external requirements, such as regulations, APIs, or competitor approaches.
4. **Reviewer agent** reviews the existing code the feature will touch and flags gaps, security risks, and technical debt to address first.
5. **Documentation agent** updates the PRD, architecture docs, and decision log.
6. **PM agent** summarises and proposes an epic with stories, then waits for your go-ahead.
7. **Coding agent** (when instructed) builds each story on a branch and opens a PR; the Reviewer checks it before a human merges.

**Core components**

| Component | Responsibility | Status |
| --- | --- | --- |
| Identity and accounts | Sign-up, login, SSO, personal / team / business accounts, workspaces, roles, invites | To build |
| Billing | Plans, seats, usage limits for agent runs | To build |
| Web and desktop apps | Board, backlog, briefings, chat, approvals, calendar, settings | To build |
| Sync service | Stores each project's `.pmagent/` on the platform with version history, and syncs a git-excluded local mirror for the CLI, Claude Code, and Codex | To build |
| Connectors | Doc sources (uploads, Drive, Notion, Confluence) and code hosts (GitHub, GitLab) | Uploads built; others to build |
| Agent engine (`agent.py`) | PM + thinking agents + coding agent, approval gate | Thinking agents built; coding agent to build |
| Issue engine (`tasks.py`, `ics.py`) | Jira-style issues, readiness, atomic claiming, calendar | Basic tasks built; issue types, epics, sprints to build |
| Tool hand-off (`handoff.py`) | Managed `AGENTS.md` / `CLAUDE.md` for Claude Code and Codex | Built |
| Project engine (`config.py`, `ingest.py`, `registry.py`) | Init / connect, folder skeleton, doc ingestion | Built |
| Approvals and jobs (`approvals.py`, `jobs*.py`, `backend.py`) | Pause and resume writes, background jobs, file locking | Built |
| CLI (`cli.py`) | Terminal client | Built |

## Agent roles and functions

Every project gets the same seven-agent team: one orchestrator, five thinking agents that never write code, and one coding agent that builds only on instruction. External tools (Claude Code, Codex) can stand in for or work beside the built-in coding agent.

| Agent | In one line | Writes its own docs? | Can edit other docs? |
| --- | --- | --- | --- |
| Project Manager | Coordinates everything; the agent you chat with | Yes: `progress/`, `current-state.md`, `roadmap.md`, issues, sprints | No: asks the owning agent |
| Product | Defines what to build | Yes: `requirements/`, `vision.md`, epics and stories | No |
| Architecture | Defines how it should work | Yes: `architecture/` | No |
| Research | Finds information | Yes: `research/` | No |
| Reviewer | Code review: checks code against what was meant to be built, plus security flaws and bugs | Yes, reports only: `reviews/` | Never; cannot touch code or other docs |
| Documentation | Keeps project knowledge organised | Yes: `decisions/` (ADRs), `project.md`, `docs/` index | Yes, for structure only (links, formatting, merging duplicates), never meaning |
| Coding agent | Implements issues | Application code on a branch | Only comments and sub-tasks on its own issue |

**There is no separate "chat agent."** Chat is how you talk to the PM. In Chat Mode the PM and every specialist can read, analyse, research, and discuss, but no one writes. When you give an instruction (Action Mode), the right agent writes, and each write waits for approval.

### Who can read and write what

Every agent can **read** the whole source of truth and the connected docs. **Writes are scoped by folder**: each agent creates and edits files only in the folders it owns, only in Action Mode, and every write or edit pauses for approval. The platform enforces this with path permissions, not just instructions, so a write outside an agent's folders is refused.

| Folder or file | PM | Product | Architecture | Research | Reviewer | Documentation | Coding agent |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `project.md`, `docs/` index | Read | Read | Read | Read | Read | **Write** | Read |
| `vision.md` | Read | **Write** | Read | Read | Read | Tidy | Read |
| `roadmap.md`, `current-state.md` | **Write** | Propose | Read | Read | Read | Tidy | Read |
| `requirements/` | Read | **Write** | Propose | Read | Read | Tidy | Read |
| `architecture/` | Read | Read | **Write** | Read | Read | Tidy | Read |
| `research/` | Read | Read | Read | **Write** | Read | Tidy | Read |
| `reviews/` | Read | Read | Read | Read | **Write** | Tidy | Read |
| `decisions/` (ADRs) | Propose | Propose | Propose | Propose | Propose | **Write** | Read |
| `progress/` | **Write** | Read | Read | Read | Read | Tidy | Read |
| `issues/`, `sprints/` | **Write** | Create stories | Create tasks | Create spikes | Create bugs | Read | Own issue: comments, sub-tasks, status |
| `agent-rules/` | Read | Read | Read | Read | Read | Read | Read |
| Application code | Read | Read | Read | Read | Read | Read | **Write** (branch only) |

**Key:** **Write** = create and edit, with approval. *Propose* = draft the change in its reply; the owner agent writes it after approval. *Tidy* = Documentation may fix structure, links, and formatting but not change meaning. *Create …* = may open new issues of that type, with approval, but not edit others' issues.

**Rules**

- `agent-rules/` is edited only by people (Owner or Admin), never by agents.
- If an agent needs a change in a folder it doesn't own, it asks the PM, who routes it to the owner. Example: the Reviewer finds the requirements are wrong, so it proposes the fix and Product makes it.
- Every write shows the file, a diff, and which agent is writing, so the approver can see exactly what changes.
- Workspace admins can tighten these defaults per project, for example making `requirements/` approval require an Admin.

### Project Manager agent

**Purpose.** The main agent and orchestrator, and the memory layer of the system. You don't need to remember which agent knows what; you tell the PM, and it routes the work.

**It keeps track of**

- What the project is, and its current phase
- Completed, in-progress, and upcoming work, across epics and sprints
- Blockers, dependencies, and priorities
- Decisions made and open questions
- Who on the team owns what, and what is waiting for whose approval

**Functions**

- Answer status questions, for example "Where are we with the delivery platform?", with phase, % progress, completed, in progress, blocked, and next recommended tasks.
- Produce the daily briefing (see Source of truth).
- Break a request into work for the right specialists, in parallel where they don't depend on each other.
- Maintain `progress/` and the task board.
- Before starting substantial work, check what is already in progress so nothing is duplicated.

### Product agent

**Purpose.** Own the product thinking. Given "I want merchants to be able to create recurring deliveries," it works through the feature rather than coding it.

**Functions**

- Ask and answer: why is this needed, and who uses it?
- Write user stories, business rules, edge cases, and acceptance criteria.
- Identify dependencies and impact on existing modules.
- Produce or update the PRD, `requirements/` files, and the roadmap.

### Architecture agent

**Purpose.** Watch the technical architecture without implementing it.

**Functions**

- Maintain the record of the stack: frontend, backend, database, cache, storage, authentication, and external services. On Kunemi, for example: Next.js, Node.js API, PostgreSQL, Redis, S3-compatible storage, the Nigeria postcode system, maps, payments, and notifications.
- Track **relationships** between entities, not just the list of parts.
- Answer impact questions. For "If we introduce PUDO locations, what is affected?" on Kunemi, it maps PUDO to Organisation, Location, Operating Zone, Parcel, Pickup, Driver, Customer, and Settlement, and names the affected modules.
- Cover database, API, integration, security, and scalability architecture.
- For non-software projects, the same agent maps the project's structure (workstreams, systems, suppliers) and the impact of changes.

### Research agent

**Purpose.** The only agent allowed to research externally.

**Functions**

- Investigate government documentation, regulations, competitors, APIs, technology, pricing, market changes, and open-source solutions.
- Check the project against the outside world, for example "Does our Kumove design still match Nigeria's new postcode system?"
- Always separate verified facts, with sources, from assumptions.
- Report findings to the PM and save them to `research/`.

### Reviewer agent (code review)

**Purpose.** Review code: every pull request and any existing part of the codebase. It answers two questions: does the code do what was meant to be built, and is it safe and sound? It is the gate between "code written" and "ready for a human to merge," and it never changes the code itself.

**What it checks, in order**

1. **Matches what was meant to be built.** Each acceptance criterion on the issue, the linked requirements, and the architecture notes and ADRs. Missing features, wrong behaviour, and scope creep (changes nobody asked for).
2. **Security flaws.** Injection (SQL, command, template), broken authentication or authorisation, missing tenant or organisation isolation, exposed secrets or keys, unsafe input handling, insecure dependencies, missing rate limits, sensitive data in logs.
3. **Correctness and bugs.** Logic errors, unhandled edge cases and error paths, race conditions, broken data migrations.
4. **Tests.** Are the acceptance criteria covered by tests? Do the tests pass and actually test the behaviour?
5. **Architecture fit.** Follows the recorded architecture and decisions; no new patterns or dependencies without an ADR.
6. **Quality and maintainability.** Readability, duplication, performance problems (N+1 queries, unbounded loops), and technical debt introduced.

**Output: a review report**

- A verdict: **Approve**, **Request changes**, or **Blocked** (a security issue that must be fixed first).
- A requirement-by-requirement table: ✓ met, ⚠ partial, ✗ missing.
- Findings, each with severity (critical, high, medium, low), file and line, what is wrong, and a suggested fix.
- Posted as a comment on the PR and saved to `reviews/`. Critical and high findings can be turned into bugs on the board, with approval.

**When it runs**

- Automatically on every PR from the coding agent, Claude Code, or Codex.
- On any human PR, if the project enables it.
- On request against existing code, for example "Review the authentication implementation against our requirements."

**Boundaries.** Reads everything; writes only its reports to `reviews/` and PR comments. It never edits code, requirements, or other docs, and never approves the merge itself. Fixes go back to the coding agent (or a developer) as "request changes".

### Documentation agent

**Purpose.** Keep the project knowledge organised so you don't end up with 50 disconnected documents.

**Functions**

- Maintain the folder structure: product docs, architecture, decisions, operations, and research.
- Write an ADR for every decision (see Decision log).
- Track documentation status, for example "Database documentation needs update," and report it in the briefing.
- Consolidate duplicates and keep cross-links current.

### Coding agent

**Purpose.** Complete the team by turning approved issues into working code, safely and reviewably.

**Functions**

- Takes one issue at a time, only when a user with permission instructs it ("build PROJ-42", or assigning the issue to the coding agent).
- Reads the issue, its acceptance criteria, and linked requirements, architecture notes, and ADRs before writing anything.
- Works in an isolated sandbox on a new branch; runs the project's tests and linters.
- Opens a pull request that links the issue and summarises changes and how to test; moves the issue to In Review.
- Logs progress and blockers on the issue; stops and asks when requirements are unclear.

**Guardrails**

- Never pushes to the main branch, merges, or deploys.
- Never changes requirements, architecture, or ADRs; it proposes changes through the PM instead.
- Its PR goes to the Reviewer, then to a human for merge.
- Spend limits per run (time, tokens) are set by the workspace plan.

**External coding tools.** Claude Code and Codex connect through a managed `CLAUDE.md` / `AGENTS.md` and the `pmagent` CLI. They follow the same rules: claim an issue when told to, log progress, and hand back for review.

## Accounts, workspaces, and access

Every user signs in, belongs to one or more workspaces, and sees only the projects their role allows. Roles decide who can put agents into Action Mode and who can approve their writes.

**Hierarchy.** User → Workspace (personal, team, or business) → Projects → Issues. A user can belong to several workspaces, for example their own personal workspace plus their company's.

**Account types**

|  | Personal | Team | Business |
| --- | --- | --- | --- |
| For | One person | Small teams and startups | Companies with several teams |
| Members | 1 (plus read-only guests) | Up to a seat limit | Unlimited seats, multiple teams |
| Projects | Limited number | Unlimited | Unlimited |
| Login | Email + password, magic link, Google, GitHub | Same | Same + SAML / OIDC SSO, enforced SSO, SCIM provisioning |
| Roles | Owner only | Owner, Admin, Member, Guest | Adds custom roles and per-project permissions |
| Agent usage | Personal allowance | Pooled across workspace | Pooled, with per-team limits |
| Admin | Basic settings | Invites, roles, billing | Audit log export, data retention, domain verification, IP allow-lists |

Prices and exact limits are an open question below.

**Roles and permissions**

| Permission | Owner | Admin | Member | Guest |
| --- | --- | --- | --- | --- |
| View projects, board, briefings | ✓ | ✓ | ✓ | ✓ (invited projects only) |
| Chat with agents (Chat Mode) | ✓ | ✓ | ✓ | ✗ |
| Create and edit issues | ✓ | ✓ | ✓ | ✗ |
| Instruct Action Mode and approve agent writes | ✓ | ✓ | ✓ (configurable) | ✗ |
| Instruct the coding agent | ✓ | ✓ | Configurable | ✗ |
| Create projects, connect repos and doc sources | ✓ | ✓ | Configurable | ✗ |
| Invite and remove members, change roles | ✓ | ✓ | ✗ | ✗ |
| Billing, plan, delete workspace | ✓ | ✗ | ✗ | ✗ |

**Account management**

- Sign-up, email verification, password reset, and two-factor authentication.
- Invite by email or shareable link; pending invites can be revoked.
- Switch between workspaces; transfer project ownership between workspaces.
- Every agent write records who instructed it and who approved it, in the audit log.
- The CLI and external tools sign in with a device login and use scoped, revocable tokens; no passwords in config files.
- Account deletion removes platform data, including each project's `.pmagent/`, after an export window; code in the user's own repos is untouched.

## Projects and connectors

A project can start three ways, and every path ends with the same `.pmagent/` on the platform and the same agent team. The code repo, if there is one, only ever holds code.

| Start from | What happens |
| --- | --- |
| **New repo** (`init`) | Creates a code repo (on the connected code host, or local git), creates the project's `.pmagent/` on the platform, and asks a few questions to seed `project.md` and `vision.md` |
| **Existing repo** (`connect`) | Creates the project's `.pmagent/` on the platform (nothing is added to the repo), imports the README, and has the Architecture agent draft `architecture/overview.md` from the codebase for approval |
| **Docs only** | For projects with no code yet (or non-software projects): no repo needed; docs are ingested into the project's `.pmagent/` on the platform |

**Connectors**

| Type | Connectors (v1) | What they do |
| --- | --- | --- |
| Doc sources | Upload (docx, pdf, pptx, xlsx, md, txt, ...), Google Drive, Notion, Confluence | Import docs into `docs/`, keeping originals plus normalized markdown; optional re-sync when the source changes |
| Code hosts | GitHub, GitLab, local git | Create or connect repos, read code for the Architecture and Reviewer agents, and let the coding agent push branches and open PRs |
| Coding tools | Built-in coding agent, Claude Code, Codex | Build issues; external tools connect via managed `CLAUDE.md` / `AGENTS.md` and the CLI |
| Notifications | Email, Slack | Approvals waiting, PRs ready for review, daily briefing |
| Calendars | iCalendar feed | Due dates and sprint dates in any calendar app |

**Connection rules**

- Connectors use OAuth with the smallest scopes needed; tokens are stored encrypted and can be revoked per workspace.
- A connector belongs to a workspace; only roles with permission can add one.
- Ingested docs are data, never instructions: agents never act on text found inside a doc or repo without the user's instruction.

## Source of truth, agent rules, decision log, and briefing

The project's memory is a structured folder, `.pmagent/`, stored on the pmagent platform. It is never the agents' chat history, and it is **never pushed to GitHub, GitLab, or any code repo**. The code host only ever sees code. Every agent reads `.pmagent/`; changes to it happen only in Action Mode.

### Where `.pmagent/` lives

- **On the platform, per project.** Encrypted at rest, scoped to the workspace, and governed by the same roles and folder permissions as everything else.
- **Version history on the platform, not git.** Every change records the file, the diff, which agent or person wrote it, who instructed it, and who approved it. Any file can be viewed at an earlier version or restored.
- **Local mirror for tools.** `pmagent pull` (and every CLI command) syncs a copy of `.pmagent/` into the local checkout so Claude Code, Codex, and the CLI can read it. The CLI adds it to `.git/info/exclude` (local-only, nothing committed) and installs a pre-commit hook that refuses any commit containing `.pmagent/`.
- **Writes go through the platform.** Changes made locally are sent to the platform API, with the same permissions and approvals, then synced back down. Tools never commit knowledge to git.
- **Coding agent sandbox.** The built-in coding agent gets a read-only copy of `.pmagent/` next to the repo checkout; its branches and PRs contain code only, and PR descriptions link to issues by key.
- **Docs-only projects need no repo at all.**
- **Export anytime.** A workspace Owner or Admin can download the full `.pmagent/` as Markdown, so leaving the platform loses nothing.

**Folder structure** (the same for every project)

```
.pmagent/                 stored on the platform, never in the code repo
├── config.yaml           project key, name, model, connectors
├── project.md            what the project is
├── vision.md
├── roadmap.md
├── current-state.md      phase and headline status
├── requirements/
│   ├── product.md
│   ├── users.md
│   ├── business-rules.md
│   └── modules/          one file per module or workstream
├── architecture/
│   ├── overview.md
│   ├── database.md
│   ├── api.md
│   └── integrations.md
├── decisions/            ADR-001.md, ADR-002.md, ...
├── research/
├── reviews/              Reviewer reports, one per review
├── progress/
│   ├── completed.md
│   ├── in-progress.md
│   └── blocked.md
├── issues/               one file per issue: PROJ-1.md, PROJ-2.md, ...
├── sprints/              one file per sprint
├── docs/                 ingested originals + normalized markdown
└── agent-rules/
    ├── base.md
    ├── project-manager.md
    ├── product.md
    ├── architecture.md
    ├── research.md
    ├── reviewer.md
    ├── documentation.md
    └── coding.md
```

**In the local checkout (git-excluded, never committed)**

```
<repo>/
├── .pmagent/             synced mirror of the platform copy
├── AGENTS.md             generated hand-off for Codex and other tools
└── CLAUDE.md             generated hand-off for Claude Code
```

`AGENTS.md` and `CLAUDE.md` are generated by the CLI and git-excluded by default, since they point at `.pmagent/`.

### Stacked agent rules

Each agent's instructions are built as `base.md` + its own role file. Rules live in the project's agent-rules/ on the platform, so you can edit how any agent behaves without touching code, and each project can have its own rules.

- **`base.md`** (every agent): "You are working on the {project name} project. Default behaviour is CHAT MODE: do not modify, create, or delete files, and do not run destructive commands. You may inspect, analyse, research, and discuss. ACTION MODE is activated only when the user explicitly instructs an action. After completing it, return to CHAT MODE. Never assume permission to modify the project."
- **Role files** add each agent's responsibilities and limits, for example: Product owns requirements, user journeys, business rules, acceptance criteria, and the roadmap, and must not write code; Research must always distinguish verified facts from assumptions; Reviewer must not modify the implementation.
- The engine ships default rules; `init` / `connect` copies them into the project, where they can be customised.

### Decision log (ADRs)

Every decision becomes an ADR, so six months later "Why did we design drivers this way?" is answered from the record, not guessed.

```
ADR-014: Multi-State Driver Routes

Decision:        Drivers may be assigned multiple routes.
Reason:          Long-distance logistics require drivers to move
                 between state hubs.
Date:            2026-09-26
Affected modules: Drivers, Routes, Hubs, Parcels, Permissions
Status:          Accepted   (Proposed | Accepted | Superseded by ADR-NNN)
```

- The PM and every specialist must cite the relevant ADR when explaining a design choice.
- If no ADR covers a question, the agent says so and offers to record a decision, rather than inventing a reason.
- Changing a past decision creates a new ADR that supersedes the old one; ADRs are never edited away.

### Daily briefing

"Give me my briefing" produces a one-screen summary, built from `progress/`, `decisions/`, `research/`, the board and current sprint, open PRs, and documentation status. Example for Kunemi:

```
KUNEMI: PROJECT BRIEFING, 26 September 2026

PROJECT HEALTH     ████████░░ 78%
CURRENT PHASE      Logistics Core

TODAY'S PRIORITIES
1. Complete Hub model
2. Review driver routing
3. Resolve postcode integration question

RECENT DECISIONS   Drivers can have multiple operating routes
                   Hubs can be state-level or zone-level
OPEN QUESTIONS     How should cross-state parcel handover work?
BLOCKERS           Postcode API documentation needs verification
RECENT RESEARCH    Nigeria Digital Postcode System; PUDO operating models
DOCUMENTATION      ✓ PRD updated  ✓ Architecture updated
                   ⚠ Database documentation needs update
```

The briefing is read-only: it never triggers a write.

## Jira-style issue tracking

Each project has a Jira-style tracker that humans and agents share. Every issue is one Markdown file in `.pmagent/issues/` on the platform (YAML fields + description + append-only log), shown as a board, backlog, and sprint view. The platform keeps each issue's full change history; nothing about issues is stored in the code repo, except issue keys referenced in branch names, commits, and PR titles.

The board is how the PM knows what is completed, in progress, blocked, and next. The `progress/` files are the human-readable summary the PM keeps in step with it, and the briefing reads both.

**Issue types and hierarchy**

| Type | Use | Parent | Typical creator |
| --- | --- | --- | --- |
| Epic | A large feature or goal, e.g. "Scheduled delivery" | none | PM / Product agent |
| Story | A user-facing slice of an epic, with acceptance criteria | Epic | Product agent |
| Task | Technical or non-user-facing work | Epic or none | PM, Architecture agent, people |
| Bug | Something broken, with steps to reproduce | Epic or none | Reviewer agent, people |
| Spike | Time-boxed research | Epic or none | Research agent |
| Sub-task | A step inside any of the above | Story, Task, or Bug | Anyone, including the coding agent |

**Keys.** Each project has a short key set at creation (e.g. `KUN`), and issues are numbered in order: `KUN-1`, `KUN-2`. Keys are what people, agents, commit messages, and PR titles use.

**Views**

- **Board:** columns by status, filter by assignee, type, label, epic, sprint.
- **Backlog:** everything not in a sprint, ordered by rank; drag to reorder.
- **Sprints (optional):** time-boxed, with a goal, start and end dates, and committed issues. Projects can run sprints or pure kanban.
- **Epic view:** each epic with its children and % complete.
- **Calendar:** due dates and sprint dates.

**Fields**

| Field | Type | Notes |
| --- | --- | --- |
| `key` | `PROJ-N` | Sequential per project, never reused |
| `type` | epic, story, task, bug, spike, sub-task | See hierarchy above |
| `title` | text | Short, imperative |
| `status` | todo, in\_progress, blocked, review, done | Workflow below; custom workflows later |
| `priority` | low, medium, high, urgent | Drives ordering |
| `assignee` | person, `coding-agent`, `claude-code`, `codex`, or empty | Agents appear as assignable members |
| `reporter` | person or agent | Who created it |
| `parent` | issue key | Epic or parent issue |
| `sprint` | sprint id | Optional |
| `estimate` | story points or hours | Optional, per project |
| `due` / `scheduled` | date or datetime | Shown on calendar |
| `depends_on` | list of keys | "is blocked by" links, validated |
| `labels` / `components` | lists | Free-form / per project |
| `links` | PRs, commits, docs, ADRs | Auto-filled by the coding agent and connectors |
| `watchers` | people | Notified on change |
| description | Markdown | Stories and bugs require acceptance criteria / repro steps |
| `## Log` | timestamped entries | Comments, @mentions, and every change, with author |

**Workflow**

&#91;embedded content: task workflow · 5 statuses\]

Only a human, or the PM agent with approval, moves a task from `review` to `done`. Coding agents stop at `review`.

**Readiness and ordering**

- A task is *ready* when its status is `todo`, every `depends_on` task is `done`, and it is unassigned or assigned to the requester.
- Ready tasks sort by priority (urgent first), then earliest due date, then oldest created.
- `next` returns an agent's own `in_progress` task before any new one, so a crashed session resumes its work.
- Claiming holds a board-wide lock, so two agents can never claim the same task.

**Calendar.** No separate calendar data exists. `pmagent calendar export` renders every task's `due` and `scheduled` dates as an iCalendar file with stable IDs, which any calendar app can import or subscribe to.

## Chat Mode vs Action Mode

Agents default to Chat Mode and change nothing; every write, by any planning agent, pauses for human approval.

|  | Chat Mode (default) | Action Mode |
| --- | --- | --- |
| Entered when | Always, unless told otherwise | You explicitly ask for a change ("create those tasks", "log that decision") |
| Agents may | Read files and board, delegate, research, review, plan | Create documents, update PRDs and architecture docs, write ADRs, create and update tasks |
| Enforcement | Prompt instruction | Approval gate on `write_file`, `edit_file`, `create_task`, `update_task`, `comment_task` |
| After | n/a | Report exactly what changed, return to Chat Mode |

**Example.** You say "I think we need to change the way drivers are assigned to zones." In Chat Mode the PM answers: the current model assumes one operating zone per driver, the newer requirement allows multiple routes, and this affects the Driver, Route, Hub, and Permission models. No files change. Only when you say "update the requirements and log that decision" does it enter Action Mode, make the changes (each approved), report "Action complete: changed 3 files," and return to Chat Mode.

**What Action Mode covers, by component**

| Action | Thinking agents | Coding agent |
| --- | --- | --- |
| Create or update docs, PRDs, requirements, architecture notes | Yes | No |
| Write ADRs | Yes (Documentation) | No |
| Create or update tasks ("issues") | Yes (PM) | Sub-tasks, status, and comments on its own issue |
| Modify application code, database migrations, configuration | Never | Yes, on instruction |
| Commit to a branch and open a pull request | No | Yes, on instruction |

**Approval behaviour**

- Each paused write shows the tool, the target, and the content (truncated if long).
- You approve or reject each action; a rejection can carry a reason that is sent back to the agent.
- Several paused actions from parallel subagents are reviewed together, one decision each.
- In a background job, a pause sets the job to `awaiting_approval` and exits; `pmagent jobs-approve` resumes it from any terminal.
- `brief` is read-only: any write it attempts is rejected automatically.

**Approvals in team and business workspaces**

- Only roles with the approve permission can approve; the person who instructed the action is shown beside the approver.
- Admins can require a second approver for coding-agent runs or for changes to requirements and ADRs.
- Pending approvals appear in the app, by email, or in Slack, and can be approved from any client.
- Merging a coding-agent PR always happens on the code host, by a human, under the repo's own branch protection.

The gate is a backstop, not the main control. The prompt keeps agents in Chat Mode; the gate guarantees nothing lands unseen.

## Functional requirements

P0 is required for public launch; P1 is targeted for launch but can slip; P2 is after launch. Status reflects the current codebase.

| ID | Requirement | Priority | Status |
| --- | --- | --- | --- |
| **Accounts and access** |  |  |  |
| FR-1 | Sign-up and login with email + password, magic link, Google, and GitHub; email verification, password reset, 2FA | P0 | To build |
| FR-2 | Personal, team, and business workspaces; one user can belong to several | P0 | To build |
| FR-3 | Roles (Owner, Admin, Member, Guest) with the permission matrix above | P0 | To build |
| FR-4 | Invite by email or link; revoke invites; remove members; change roles | P0 | To build |
| FR-5 | Audit log of every agent write: who instructed, who approved, what changed | P0 | Partial: per-issue logs only |
| FR-6 | CLI and external tools sign in with device login and scoped, revocable tokens | P0 | To build |
| FR-7 | Business: SAML / OIDC SSO, enforced SSO, SCIM, custom roles, audit export, data retention | P1 | To build |
| FR-8 | Plans, seats, usage limits for agent runs, and self-serve billing | P1 | To build |
| **Projects and connectors** |  |  |  |
| FR-9 | Start a project from a new repo, an existing repo, or docs only | P0 | Partial: local `init` / `connect` built |
| FR-10 | GitHub and GitLab connectors: create or connect repos, read code, push branches, open PRs | P0 | To build |
| FR-11 | Doc ingestion from upload (any common format) | P0 | Built |
| FR-12 | Doc connectors for Google Drive, Notion, Confluence, with re-sync | P1 | To build |
| FR-13 | On `connect`, the Architecture agent drafts an architecture overview from the codebase for approval | P1 | To build |
| FR-14 | Slack and email notifications for approvals, PRs, and briefings | P1 | To build |
| **Source of truth and rules** |  |  |  |
| FR-15 | Scaffold the full `.pmagent/` structure, including `issues/`, `sprints/`, `progress/`, reviews/, and `agent-rules/` | P0 | Partial |
| FR-16 | Agent prompts built from `base.md` + role file; defaults ship with the product and are editable per project | P0 | To build |
| FR-17 | Business workspaces can set org-wide base rules that every project inherits | P2 | To build |
| FR-18 | `.pmagent/` is stored only on the platform with per-file version history; a git-excluded local mirror syncs through the API; a pre-commit hook blocks committing it; full Markdown export on demand | P0 | To build |
| **Thinking agents** |  |  |  |
| FR-19 | PM answers status, produces the daily briefing (health, phase, priorities, decisions, questions, blockers, research, doc status, sprint, open PRs) | P0 | Partial |
| FR-20 | PM routes a feature through Product, Architecture, Research, Reviewer, Documentation, in parallel where independent | P0 | Built (prompt) |
| FR-21 | Product produces epics and stories with acceptance criteria | P0 | Partial: flat tasks only |
| FR-22 | Reviewer code-reviews every agent PR (and existing code on request) against acceptance criteria, then for security flaws, bugs, tests, architecture fit, and quality; returns a verdict, a ✓ / ⚠ / ✗ table, and findings by severity; saves to reviews/ and comments on the PR; all other writes denied | P0 | Partial: no repo or PR access |
| FR-23 | Documentation writes ADRs and tracks doc status; agents cite ADRs or say none exists | P0 | Partial |
| **Coding agent** |  |  |  |
| FR-24 | Built-in coding agent builds one issue on instruction, in a sandbox, on a new branch | P0 | To build |
| FR-25 | Runs the project's tests, opens a PR linked to the issue, moves it to review | P0 | To build |
| FR-26 | Never pushes to main, merges, deploys, or edits requirements / ADRs | P0 | To build |
| FR-27 | Claude Code and Codex hand-off through managed `CLAUDE.md` / `AGENTS.md` and the CLI, on instruction only | P0 | Built (currently claims at session start) |
| FR-28 | Per-run spend limits by plan | P1 | To build |
| **Issue tracking** |  |  |  |
| FR-29 | Issue types (epic, story, task, bug, spike, sub-task), parent links, sequential keys per project | P0 | To build: today flat tasks with hex ids |
| FR-30 | Board, backlog with ranking, epic view, filters | P0 | Partial: CLI list only |
| FR-31 | Optional sprints with goal and dates | P1 | To build |
| FR-32 | Dependencies, readiness, priority ordering, due dates, calendar feed | P0 | Built |
| FR-33 | Comments, @mentions, watchers | P1 | Partial: comments only |
| FR-34 | Custom workflows per project | P2 | To build |
| **Chat Mode vs Action Mode** |  |  |  |
| FR-35 | Chat Mode default; Action Mode only on explicit instruction; auto-return; report what changed | P0 | Built |
| FR-36 | Every agent write pauses for approval by a permitted role; optional second approver | P0 | Partial: single local approver |
| **Clients** |  |  |  |
| FR-37 | Web app: chat, briefings, board, backlog, approvals, settings | P0 | To build |
| FR-38 | CLI with the same capabilities | P0 | Built for local use |
| FR-39 | Desktop app | P2 | To build |
| FR-40 | Import from Jira, Linear, or GitHub Issues | P2 | To build |
| FR-41 | Per-agent folder permissions (Write / Propose / Tidy / Read) enforced by the platform, as in the matrix under Agent roles; writes outside an agent's folders are refused; admins can tighten per project | P0 | Partial: only the Reviewer's deny rule exists |

## Non-functional requirements

| Area | Requirement |
| --- | --- |
| Security | Passwords hashed with a modern algorithm; 2FA; OAuth tokens and secrets encrypted at rest; TLS everywhere; scoped, revocable API tokens. |
| Multi-tenancy | Strict workspace isolation: no data, agent context, or connector token crosses workspaces. Every query is scoped by workspace. |
| Agent safety | No agent write without instruction and approval. Each agent can write only to the folders it owns (path permissions enforced by the platform); the Reviewer only to reviews/. Coding agent runs in an isolated sandbox with no access to production credentials and cannot push to protected branches. Text in docs and repos is treated as data, never instructions. |
| Privacy | Project content is not used to train models. Data export and deletion on request. Region choice for business plans (later). |
| Data ownership | `.pmagent/` never leaves the platform for a code host: it is never pushed to GitHub, GitLab, or any repo, and coding-agent PRs contain code only. Customers can export the full `.pmagent/` as Markdown at any time, so leaving the platform loses nothing. |
| Concurrency | Many users, agents, and jobs on one project at once: per-file locks, atomic writes, atomic issue claiming, conflict-safe sync with git. |
| Reliability | Web app 99.9% monthly uptime target; agent runs resumable after failure; failed runs clearly marked. |
| Performance | Board and backlog load in under 1 second for 5,000 issues; briefing in under 60 seconds. |
| Model choice | Anthropic, OpenAI, or Google models, set per workspace or project. |
| Compliance | SOC 2 Type II and GDPR readiness for the business plan (roadmap). |
| Observability | Tracing of every agent run, visible to workspace admins; usage dashboards. |
| Maintainability | Engine modules are UI-agnostic; web, desktop, and CLI are clients of one API. Dependencies pinned. |

## User flows

**1. Sign up and create a workspace**

1. Sign up with email, Google, or GitHub; verify email.
2. Choose Personal, or create a Team or Business workspace and name it.
3. Team and business: invite members by email, assign roles.

**2. Start a project**

1. Choose: new repo, connect an existing repo (GitHub, GitLab, local), or docs only.
2. Set the project key (e.g. `KUN`) and a one-line description.
3. Connect doc sources or upload files; they are ingested into `docs/`.
4. For an existing repo, approve the Architecture agent's draft overview.
5. Optionally enable Claude Code / Codex hand-off, which writes `CLAUDE.md` and `AGENTS.md`.
6. First briefing.

**3. Daily briefing and status**

1. Each morning: "Give me my briefing" in the app, CLI, or Slack.
2. During the day: "Where are we with the delivery platform?" returns phase, %, done, in progress, blocked, and next.

**4. Idea to epic**

1. "I want to add scheduled delivery."
2. The PM routes it through Product, Architecture, Research, and the Reviewer.
3. The PM proposes an epic, stories with acceptance criteria, and an ADR. Nothing is written yet.
4. "Create the epic and log the decision." Each write is approved by a permitted role.

**5. Build with the coding agent**

1. A member assigns `KUN-42` to the coding agent, or says "build KUN-42."
2. If the workspace requires it, a second approver confirms the run.
3. The coding agent builds on a branch, runs tests, opens a PR, and moves the issue to review.
4. The Reviewer checks the PR against acceptance criteria and posts a report.
5. A human merges on GitHub or GitLab; the issue moves to done.

**6. Build with Claude Code or Codex**

1. A developer tells Claude Code to take `KUN-43`.
2. Claude Code reads `CLAUDE.md`, claims the issue via the CLI, builds it, and hands back for review.
3. Review and merge as in flow 5.

**7. Impact and "why" questions**

1. "If we introduce PUDO locations, what is affected?" The Architecture agent returns the entity map and affected modules.
2. "Why can drivers operate across multiple states?" The PM answers from the ADR, or says none exists and offers to record one.

**8. Review what's built**

1. "Review the authentication implementation against our requirements."
2. The Reviewer reads the repo and returns the ✓ / ⚠ / ✗ table; gaps become bugs or stories on approval.

## Roadmap

Five phases take the product from a local tool proven on Kunemi to a public multi-tenant platform. Each is gated on exit criteria; target dates are an open question.

| Phase | Scope | Exit criteria |
| --- | --- | --- |
| 1: Engine, proven on Kunemi | Full folder structure, stacked agent rules, thinking agents, ADRs, briefing, Reviewer with repo read, Jira-style issue types and keys (local CLI; .pmagent/ kept local and git-excluded until the platform ships) | A week of trusted daily briefings on Kunemi; one feature from idea to approved epic, stories, and ADR |
| 2: Coding agent | Built-in coding agent (sandbox, branch, tests, PR), GitHub connector, Reviewer on PRs, instruction-only Claude Code / Codex hand-off | 10 issues built by the coding agent on Kunemi; ≥ 6 merged without major rework; zero pushes to main |
| 3: Platform beta (personal + team) | Accounts, login, workspaces, roles, invites, web app (chat, board, backlog, approvals), platform-hosted .pmagent/ with version history and local mirror sync, doc connectors, notifications | 20 design-partner teams onboarded; first briefing in < 10 min; no cross-workspace data leaks in security review |
| 4: Public launch | Billing and plans, usage limits, sprints, GitLab, onboarding polish, docs site | Self-serve sign-up to paid without help; uptime ≥ 99.9% for 30 days |
| 5: Business | SSO, SCIM, custom roles, audit export, data retention, desktop app, Jira / Linear import | First business customer live; SOC 2 audit started |

## Risks and open questions

**Risks**

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Coding agent writes insecure or wrong code | High | Sandbox, branch-only, tests required, Reviewer pass, human merge, spend limits |
| Cross-workspace data leak | High | Workspace-scoped queries everywhere, isolation tests, external security review before beta |
| Prompt injection through ingested docs or repo text | High | Treat all ingested content as data; writes still need a human instruction and approval |
| Agents answer "why" from memory instead of ADRs | High: project drift returns | Base rules require ADR citation; Documentation audits chat decisions weekly |
| Local mirror drifts from the platform copy | Medium | Platform is authoritative; mirror syncs on every CLI command; conflicts shown for a human to resolve |
| Model and compute costs exceed plan revenue | Medium | Per-plan usage limits, cheaper models for routine work, metering from day one |
| Crowded market (Jira, Linear, AI coding tools) | Medium | Position as the team around your coding tools, not a replacement; keeps knowledge beside the code without cluttering the repo; works with Claude Code and Codex |
| Approval fatigue leads to rubber-stamping | Medium | Clear diffs, batched related writes, optional second approver |
| `deepagents` / model API changes | Medium | Pinned versions, contract tests, provider abstraction |
| .pmagent/ accidentally committed and pushed to a code host | High: private plans and decisions exposed | CLI adds .git/info/exclude and a pre-commit hook; coding-agent PRs are checked to contain no .pmagent/ files; connect warns if the repo already tracks one |

**Open questions**

- [ ] Product name: keep "pmagent" or choose a brand name before public launch?
- [ ] Pricing: per-seat, per-usage, or both? What are the free limits for Personal?
- [ ] Should open-source projects be able to opt in to publishing a read-only snapshot of selected .pmagent/ docs (e.g. the roadmap)?
- [ ] Where does the coding agent sandbox run: our cloud only, or also on the customer's machine via the CLI?
- [ ] Should the PM be allowed to close issues after a passing review without a separate approval?
- [ ] Are custom workflows needed for launch, or is the fixed five-status workflow enough?
- [ ] What are the target dates for each phase?
