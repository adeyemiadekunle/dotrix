# dotrix

Dotrix — The AI workspace for building software.

"Dotrix is inspired by linear algebra — dots represent specialised components, while the matrix represents the relationships between them. Dotrix brings AI agents, knowledge, tasks and tools together into one coordinated workspace"

An AI project team for software projects. Agents write and maintain a project's documents and
board, explain its code, and hand coding to Kai, the coding agent. People decide how much goes
through without asking, and every change is in the audit log.

- **A team of agents you configure:**
  - The Project Manager (Nova) and five specialists: Product, Architecture, Research, Reviewer,
    and Documentation (Echo). Kai codes.
  - Owners and admins can edit any of them, or create their own: instructions, model, tools,
    folder access, autonomy rules, budgets. Each person can add their own instructions and model
    for their runs.
- **One source of truth per project:** a versioned `.dotrix/` knowledge store (requirements,
  architecture, decisions, research, the repository's wiki), a Jira-style board, and a project
  graph that links them.
- **You decide what goes through:** approval modes (Manual, Accept edits, Auto) work the same in
  chat and coding. The workspace's owners cap them, and a pause means Manual for everyone.
  Closing issues, merging, and agent rules always need a person. Every change is audited.
- **Runs that survive:** a run whose worker stops goes on from where it stopped, on another
  worker, without making a change twice. A coding run whose push or PR is uncertain is settled
  from what GitHub shows.
- **Agents that work in the background:** automations run on a schedule or when people change
  things. Examples: "Keep documents current" after approved changes, a weekly status, triage of
  new issues, a watch on a topic.
- **Agents that learn:**
  - Rules set for the whole workspace, layered under each project's own.
  - Skills (procedures agents follow) and folder templates.
  - Lessons proposed from rejected changes and dismissed results, which owners accept or
    decline.

Product spec: [docs/prd.md](docs/prd.md). The agents' design: [docs/agents-v2.md](docs/agents-v2.md).
The direction: [strategy and roadmap](docs/dotrix-product-strategy-and-roadmap.md),
[durable agent harness](docs/dotrix-durable-agent-harness.md),
[hybrid execution](docs/dotrix-hybrid-execution-architecture.md), and the
[Repository Knowledge skill](docs/dotrix-repository-knowledge-skill.md). What's built, item by
item: [CLAUDE.md](CLAUDE.md).

## What you can do today

- **Chat** with the project's agents, in one Chat for the workspace (or from Home's ask box):
  - Type @ to pick the project (or all projects) and who answers (Auto brings in the
    specialists it needs); pick the model.
  - **Work modes:** each message is Discuss, Plan, Build, or Review.
    - Plan saves versions of the conversation's plan, with "Build this plan".
    - Only Build engages Kai.
    - Review reads what Kai did in this conversation.
  - **Approvals:** pick Manual, Accept edits, or Auto beside the mode (only the modes you may
    use). In Manual, approve or reject each change, with diffs.
  - Follow what each agent is doing as it works. A reply keeps its steps afterwards, and a
    dropped connection picks up where it was.
  - A run stopped at its model's limit, or interrupted, continues from where it stopped.
  - Ask across several projects at once; those conversations are read-only.
- **Plan and track:**
  - Board and List for each project, with an Overview and Activity.
  - My Tasks across the workspace.
  - ⌘K search over issues, documents, projects, people, and agents.
- **Keep knowledge current:**
  - Documents with full history, restore, and export.
  - Uploads converted to Markdown.
  - Hybrid search (keywords and meaning, with pgvector).
  - The project graph, which shows what relates to what, what a change affects, and which
    documents may be out of date. It's drawn in Knowledge.
- **Explain the repository** (Knowledge → Coverage):
  - Each push takes an inventory: every tracked file, what it is, and which of 12 knowledge
    domains it's evidence for. What isn't read is listed with why.
  - Coverage shows each domain as read, partly read, not read, or a gap, with what to ask
    for.
  - "Explain the repository" has Echo write `docs/wiki/` pages. Every claim cites its source as
    `path:line`, with its basis and gaps, and pages go through approval like any document.
  - A page goes stale when the code it cites changes. Editors are notified, and "Refresh stale
    pages" updates them.
  - Dependencies come from manifests and their lockfiles (npm, pnpm, yarn, Python, Cargo, Go).
  - Every run, and Kai's brief, starts from the wiki pages that bear on the work.
- **Research** on the web (Tavily): every claim is checked against the page it cites, and
  reports can be saved as research notes.
- **Coding with Kai:** "Start coding" on an issue, Build mode in Chat, or a new session in Chat's
  Code tab (type @ or / to pick the issue).
  - Kai runs headless in a sandbox from a brief: the issue, its acceptance criteria, the
    documents it links to, and the repository's wiki. Underneath, Kai is Claude Code, Codex, or
    OpenCode. OpenCode runs on any provider's model.
  - It runs on the same keys as chat: yours, where the organisation allows it, else the
    workspace's.
  - The sandbox is a Docker container per run whose only way out is the model API, or an
    OpenShell sandbox.
  - In Manual a run waits for an approver. In Accept edits and Auto it starts at once. You can
    follow it as it works, and stop it.
  - Every fix gets its own branch on the project's repo and a PR; follow-ups add commits to the
    same branch and PR. The issue moves to review, and the Reviewer reads the PR.
  - Sessions keep their sandbox warm between turns and resume where they left off.
  - A session shows its repo, the branch it started from and its own, its commits, and each
    changed file.
  - A run cut off mid-push is recovered from what GitHub shows.
  - Guardrails: Kai never holds a GitHub token, and nothing is pushed to the default branch.
    Changes to `.dotrix/` or CI configuration (all of `.github/`) are refused, and a person merges.
  - Setup: [infra/coding/README.md](infra/coding/README.md).
- **Notifications:**
  - What happens: approvals waiting, decisions, mentions, assignments, findings, changes to
    issues you watch, runs stopped at a limit, and wiki pages a push made stale.
  - Where: in the app (one Inbox, with what people and agents send you) and by email, as it happens, as a daily digest, or off.
- **Teams:**
  - Personal workspaces and organisations, with roles and invites.
  - Restricted projects.
  - Sign-in with a password, an email link, or GitHub.
  - Sessions per device.
- **CLI and MCP:** `dotrix` chats, briefs, triages, reviews, and works the board from a
  terminal. Its MCP server gives Claude Code and Codex the board, the documents, and the graph.

## What's next

The first milestone (M1 in the [roadmap](docs/dotrix-product-strategy-and-roadmap.md)): one
coding run interrupted on purpose, recovered, and reviewed in the same conversation.

- **One conversation for chat and code:**
  - Kai's turns inline in the conversation: status, branch, PR, changed files, Stop, and
    Recover.
  - Coding sessions joined to the conversations list, and one composer for both.
  - The side panel: Changes, Files, and Terminal from real sessions.
- **Coding:**
  - OpenCode's first turn on a real model, and its image in the Docker sandbox.
  - Turns committed one by one, and a turn's diff accepted before it's pushed (A2).
  - The board and documents available to Kai inside its sandbox, and running the app it
    builds.
  - PR checks back on the board.
- **Where coding runs:** in the cloud on dotrix's own hosts (hardened with gVisor and
  per-workspace limits), or locally from the desktop app or CLI in a worktree of your own
  checkout.
- **Models:** retry a provider's rate limit with backoff, a per-workspace limit on runs working
  at once with a queue, and usage per person.
- **Repository knowledge:** more manifests (Gemfile, composer, Gradle, Maven), and the discovery
  run measured on real models.
- **The web app on TanStack Query:** Chat and its Code tab read the API through TanStack Query;
  the other screens still load into the store (`data/live.ts`).
- **Background commit review:** a code graph and the blast radius of each push.
- **Space:** workspace-level knowledge, and ideas before a project exists.
- **Deployment:** production on one VPS with Dokploy ([deploy/README.md](deploy/README.md)).
  It needs a domain with HTTPS, `DOTRIX_ENCRYPTION_KEY`, and a model key for coding runs.

## Monorepo layout

```
apps/
  backend/      FastAPI platform API: accounts, workspaces, projects, knowledge, issues, agents,
                approvals, automations, notifications, the graph, connectors (Python)
  cli/          `dotrix` terminal client + MCP server for Claude Code / Codex (Python)
  web/          Web app (Vite + React)
  desktop/      Desktop shell around the web app (Electron)
packages/
  engine/       UI-agnostic agent engine: agent contracts, pipelines, approvals, tools (Python)
  api-client/   Typed client for the backend API, generated from its OpenAPI schema
  ui/           shadcn/ui components, the chat kit, and the theme
infra/          Local services (Postgres with pgvector, Redis, MinIO) and the coding sandbox's
                image and egress proxy (infra/coding)
docs/           The PRD, the engine, the agents v2 spec, the coding agent, and the proposed direction
```

Python is a [uv](https://docs.astral.sh/uv/) workspace; TypeScript is a
[pnpm](https://pnpm.io/) workspace run by [Turborepo](https://turbo.build/). The web app, the
desktop app, and the CLI are all clients of one API. The engine never depends on a UI.

## Getting started

You need Python 3.11+, uv, Node 22+, pnpm 11, and Docker (for Postgres, Redis, and MinIO).

```bash
uv sync                  # Python: engine, CLI, backend + dev tools
pnpm install             # TypeScript apps and packages
cp .env.example .env     # then replace every change-me and set a model API key
```

Run it:

```bash
pnpm db:up && pnpm db:migrate   # Postgres, Redis, MinIO (localhost only), then the migrations
pnpm dev:backend         # API on http://localhost:8000 (agents need a model key in .env)
pnpm dev:worker          # only with DOTRIX_JOBS=worker: runs survive API and worker restarts
pnpm dev:web             # web on http://localhost:3000
pnpm dev:desktop         # Electron window on the web app
uv run dotrix --help    # CLI
```

**Configuration** (all in `.env`, explained in [.env.example](.env.example)):
- **Required:** a model key (Anthropic, OpenAI, or Google) and `DOTRIX_DEFAULT_MODEL`.
- **Optional:**
  - `DOTRIX_EMBEDDING_MODEL`: search by meaning; without it, search uses keywords only.
  - `DOTRIX_TAVILY_API_KEY`: web research through Tavily.
  - `DOTRIX_SENDLY_API_KEY`: real email delivery.
  - The GitHub sign-in and GitHub App settings: sign-in with GitHub and connected repos.
  - `DOTRIX_CODING_AGENT`: which tool Kai runs (`auto`: Claude Code, or Codex with only an
    OpenAI key; `opencode`, with `DOTRIX_CODING_OPENCODE_MODEL`, on any provider's model).
  - `DOTRIX_CODING_SANDBOX`: coding runs: `docker` (build the image first:
    `docker build -t dotrix-coding:latest infra/coding`), `openshell`, or `local` for
    development only. Staging and production also need `DOTRIX_CODING_FORK_OWNER`, the
    organisation coding branches are pushed to as a fork. See
    [infra/coding/README.md](infra/coding/README.md).
- **Limits:**
  - `DOTRIX_RUN_TOKEN_BUDGET`: tokens per agent run.
  - `DOTRIX_AUTOMATION_DAILY_RUNS` and `DOTRIX_AUTOMATION_DAILY_TOKENS`: automation runs and
    tokens per workspace per day.

## Install the CLI

The `dotrix` command installs on its own (Python 3.11+ and [uv](https://docs.astral.sh/uv/)):

```bash
uv tool install "git+https://github.com/adeyemiadekunle/dotrix#subdirectory=apps/cli"
```

- On Windows, run `uv tool update-shell` once (then open a new terminal) so `dotrix` is on your PATH.
- Without uv: `pipx install "git+https://github.com/adeyemiadekunle/dotrix#subdirectory=apps/cli"`.
- Point it at your server with `DOTRIX_API_URL` (or `--api-url` on `login`). The default is
  `http://127.0.0.1:8000` until a hosted platform exists.
- Upgrade with `uv tool upgrade dotrix`; remove with `uv tool uninstall dotrix`.

## The CLI with the platform

```bash
dotrix login                                   # device login; the token goes to your OS keychain
cd ~/code/kunemi && dotrix connect             # link this checkout to its project (found by the git remote)
dotrix pull                                    # refresh the .dotrix/ mirror (only what changed)
dotrix chat --agent research                   # talk to the team; approve or reject each change inline
dotrix brief                                   # a summary of what changed (read-only)
dotrix triage "Drivers see the wrong zone"     # the PM triages a report into an issue (waits for approval)
dotrix review KUN-12                           # the Reviewer checks an issue against its acceptance criteria
dotrix issue list --mine                       # your issues (or --as claude-code for an agent's)
dotrix issue claim KUN-42 --as claude-code     # coding tools act as themselves and stop at review
dotrix issue done KUN-42                       # only a person closes
dotrix handoff install --register              # Claude Code / Codex via MCP: board, documents, graph
dotrix logout
```

**Setting a project up, and working in it.** Owners and admins set a project up once, on the
web or with the CLI:
- Create it (`dotrix connect`, or `dotrix init` for a new repo).
- Add its documents (`dotrix docs-add <files>`).
- Have the Architecture agent draft its overview (`dotrix architecture draft`).

Everyone else just runs `dotrix connect` in their own checkout: it links to the project by the
git remote and changes nothing.

`DOTRIX_TOKEN` overrides the keychain for CI. Unlinked repos keep working with local files
(`--local`, `dotrix task …`).

## API documentation

With the backend running (`pnpm dev:backend`):

- **Swagger UI**: http://localhost:8000/docs. Click **Authorize** and paste an `access_token`
  from `/v1/auth/login` to try routes that need you to be signed in.
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI schema**: http://localhost:8000/openapi.json, also committed at
  [packages/api-client/openapi.json](packages/api-client/openapi.json)

The TypeScript client in `packages/api-client` is generated from that schema. After changing
any route or schema, run `pnpm openapi` and commit the result; CI fails if they're out of date.
Set `DOTRIX_DOCS_ENABLED=false` to turn the docs off.

## Checks

CI runs all of these:

```bash
uv run ruff check apps packages && uv run pytest   # lint; unit and integration tests (need Postgres)
pnpm build && pnpm typecheck
pnpm test                                          # web unit tests (Vitest)
pnpm knip                                          # unused files, exports and dependencies (CI fails on unused files and dependencies)
pnpm --filter @dotrix/web e2e                     # browser tests on a rule-based model
```
