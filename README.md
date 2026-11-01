# dotrix

Dotrix — The AI workspace for building software.

"Dotrix is inspired by linear algebra — dots represent specialised components, while the matrix represents the relationships between them. Dotrix brings AI agents, knowledge, tasks and tools together into one coordinated workspace"

An AI project team for software projects. Agents write and maintain a project's documents and
board, explain its code, and hand coding to Kai, the coding agent. People decide how much goes
through without asking, and every change is in the audit log.

- **A fixed team:**
  - **Nova** leads Chat and brings in the specialists: **Lyra** (product), **Orion**
    (architecture), **Vega** (research), **Juno** (reviews) and **Echo** (documentation).
  - **Kai** codes, in Codes.
  - Each workspace and project can add guidance; each person can add up to 2,000 characters of
    instructions and pick a model for their own runs. Every change to these is versioned and
    audited.
- **Your own model keys:** every person connects their own provider key (Account → Your
  models). Every run, chat or coding, uses only that key: there are no workspace or server
  keys.
- **One source of truth per project:** a versioned `.dotrix/` knowledge store (requirements,
  architecture, decisions, research, the repository's wiki), a board, and a project graph that
  links them.
- **You decide what goes through:** approval modes (Manual, Accept edits, Auto) work the same in
  chat and coding. The workspace's owners cap them, and a pause means Manual for everyone.
  Closing issues, merging, and agent rules always need a person. Every change is audited.
- **Runs that survive:** a run whose worker stops goes on from where it stopped, on another
  worker, without making a change twice. A coding run whose push or PR is uncertain is settled
  from what GitHub shows.
- **Agents that work in the background:** automations run on a schedule or when people change
  things: "Keep documents current" after approved changes, a weekly status, triage of new
  issues, a watch on a topic.
- **Agents that learn:** workspace rules layered under each project's, skills (procedures
  agents follow), folder templates, and lessons proposed from rejected changes and dismissed
  results.

Product spec: [docs/prd.md](docs/prd.md). The team: [docs/nova-team.md](docs/nova-team.md).
Coding: [docs/coding-agent.md](docs/coding-agent.md). What's built, item by item, and what's
left: [CLAUDE.md](CLAUDE.md).

## What you can do today

- **Chat** with the project's team (or from Home's ask box):
  - Pick the project in the card when you start, or type @ in the message box; "All projects"
    asks across several at once, read-only.
  - **Work modes:** each message is Discuss, Plan, Build, or Review. Plan saves versions of the
    conversation's plan, with "Build this plan"; only Build engages Kai; Review reads what Kai
    did in this conversation.
  - **Approvals:** Manual, Accept edits, or Auto (only the modes you may use). In Manual you
    approve or reject each change, with diffs.
  - Nova thinks first, and you see its thinking and what each agent is doing as it works. A
    reply keeps its steps afterwards, and a dropped connection picks up where it was.
  - Queue a follow-up or steer Nova while it works; Stop cancels both.
  - A run stopped at its model's limit, or interrupted, continues from where it stopped.
  - **Two runtimes:** DeepAgents (the default) or fx, picked per conversation. Both go through
    the same approvals.
- **Coding with Kai** (Codes, below Chat in the sidebar):
  - Start from "Start coding" on an issue, Build mode in Chat, or "New session" in Codes.
  - **Where it codes:** a cloud sandbox, or your own computer through the desktop app or
    `dotrix runner`.
  - **The model** is picked per session, and the engine follows it. The engine is Claude Code,
    Codex, OpenCode or fx, set in Account → Your models; people only ever see Kai.
  - Kai works from a brief: the issue, its acceptance criteria, linked documents, the
    repository's wiki, and a definition of done.
  - Every session has its own branch and PR; follow-ups add commits to it. In Manual, a turn
    waits to start and again before it's pushed. Changes to files CI runs always wait for a
    person. A pushed turn can be reverted.
  - **Juno** reviews Kai's PR and posts the review on GitHub. When CI fails, Juno reads the failed
    logs, and "Ask Kai to fix" starts a follow-up.
  - Sessions follow Claude Code's session view: the turns, a details column (environment,
    branch, usage, outputs, the PR and its checks), and panes for Changes, Files, Terminal and
    Review.
  - Guardrails: Kai never holds a GitHub token, nothing is pushed to the default branch,
    `.dotrix/` and CI configuration are refused, and a person merges.
- **Plan and track:** Board and List for each project, with an Overview and Activity; My Tasks
  across the workspace; ⌘K search over issues, documents, projects, people, and agents.
- **Keep knowledge current:**
  - Documents with full history, restore, and export.
  - Uploads converted to Markdown.
  - Hybrid search (keywords and meaning, with pgvector).
  - The project graph: what relates to what, what a change affects, and which documents may be
    out of date.
- **Explain the repository** (Knowledge → Coverage):
  - Each push takes an inventory of every tracked file and the knowledge domains it covers.
  - "Explain the repository" has Echo write `docs/wiki/` pages, every claim cited as
    `path:line`.
  - A page goes stale when the code it cites changes; "Refresh stale pages" updates it.
  - Dependencies come from manifests and lockfiles, checked against OSV for known
    vulnerabilities.
- **Research** on the web (Tavily): every claim is checked against the page it cites.
- **Notifications:** approvals waiting, decisions, mentions, assignments, findings, changes to
  issues you watch, runs stopped at a limit, and stale wiki pages. They arrive in the Inbox, by
  email as they happen, or as a daily digest.
- **Teams:**
  - Personal workspaces and organisations, with roles, invites, and restricted projects.
  - Sign-in with a password, an email link, or GitHub.
- **Desktop app** (Windows first): the web app in a window. It codes local turns on your
  computer, shows a turn's live worktree, updates itself, and shows What's new.
- **CLI and MCP:** the same chat, coding sessions and board from a terminal. The MCP server
  gives Claude Code and Codex the board, the documents, and the graph.
- **Admin console:** for whoever runs dotrix. It shows the platform's health, runs, failures,
  coding, workspaces and audit log, across every workspace, never what people wrote.

## What's next

The full list, most urgent first, is in [CLAUDE.md](CLAUDE.md) under "Remaining work". In short:

- **Production:**
  - A domain with HTTPS on Dokploy ([deploy/README.md](deploy/README.md)).
  - Docker Cloud sandboxes on a real account.
  - The engines on their other providers' paid models.
  - Hardening the cloud sandbox (gVisor, per-workspace limits).
  - Retries and a queue when several people share a key.
- **Codes:** live text instead of polling, usage per session, and subagents' events nested.
- **Chat:**
  - fx tested on real models before it becomes a default.
  - Specialist memory controls.
  - Steering and work modes in conversations across projects.
- **Local coding:**
  - Docker Sandboxes (`sbx`) checked on a real machine.
  - Signing and macOS for the desktop app.
  - Folders without a remote.
- **Later:**
  - A code graph and blast radius.
  - Running the app Kai builds.
  - Workspace-level knowledge and ideas.
  - More connectors (Slack, GitLab, Drive).

## Monorepo layout

```
apps/
  backend/      FastAPI platform API: accounts, workspaces, projects, knowledge, issues, agents,
                approvals, automations, notifications, the graph, coding, connectors (Python)
  cli/          `dotrix` terminal client, local coding runner, and MCP server (Python)
  web/          Web app, app.dotrix.cc (Vite + React)
  desktop/      Desktop app around the web app; codes local turns (Electron)
  admin/        Admin console for whoever operates dotrix (Vite + React)
  site/         Public site, dotrix.cc (Vite + React, prerendered)
packages/
  engine/       UI-agnostic agent engine: the team, pipelines, approvals, tools, runtimes (Python)
  api-client/   Typed client for the backend API, generated from its OpenAPI schema
  ui/           shadcn/ui components, the chat kit, and the design
infra/          Local Postgres (with pgvector), Redis and RustFS; dotrix in Docker; the coding
                sandbox's image and egress proxy (infra/coding)
deploy/         Production on one VPS with Dokploy
docs/           The PRD, the engine, the team, the coding agent, and the proposed direction
```

Python is a [uv](https://docs.astral.sh/uv/) workspace; TypeScript is a
[pnpm](https://pnpm.io/) workspace run by [Turborepo](https://turbo.build/). The web app, the
desktop app, the admin console and the CLI are all clients of one API. The engine never depends
on a UI.

## Getting started

You need Python 3.11+, uv, Node 22+, pnpm 11, and Docker (for Postgres, Redis, and RustFS).

```bash
uv sync                  # Python: engine, CLI, backend + dev tools
pnpm install             # TypeScript apps and packages
cp .env.example .env     # then replace every change-me
```

Run it on your machine:

```bash
pnpm db:up && pnpm db:migrate   # Postgres, Redis, RustFS (localhost only), then the migrations
pnpm dev:backend         # API on http://localhost:8000
pnpm dev:worker          # with DOTRIX_JOBS=worker: runs survive API and worker restarts
pnpm dev:web             # web app on http://localhost:3000
pnpm dev:desktop         # Electron window on the web app
uv run dotrix --help     # CLI
```

Or run all of dotrix in Docker:

```bash
pnpm docker:up           # web http://localhost:3080, admin :3300, site :3200, API :8000, worker
```

Then sign up, open Account → Your models and connect your own provider key: agents run on it.

**Configuration** (all in `.env`, explained in [.env.example](.env.example)):
- **Required:**
  - `DOTRIX_ENCRYPTION_KEY`: a Fernet key that encrypts people's model keys and saved coding
    sessions.
  - The Postgres and storage passwords.
- **Optional:**
  - `DOTRIX_EMBEDDING_MODEL`: search by meaning; without it, search uses keywords only.
  - `DOTRIX_TAVILY_API_KEY`: web research through Tavily.
  - `DOTRIX_SENDLY_API_KEY`: real email delivery.
  - The GitHub sign-in and GitHub App settings: sign-in with GitHub, connected repos, and
    coding.
  - `DOTRIX_CODING_SANDBOX`: where cloud coding turns run:
    - `docker`: build the image first, `docker build -t dotrix-coding:latest infra/coding`.
    - `docker-cloud`: Docker's own cloud sandboxes.
    - `openshell`.
    - `local`: development only.

    Staging and production also need `DOTRIX_CODING_FORK_OWNER`. See
    [infra/coding/README.md](infra/coding/README.md).
  - `DOTRIX_SPECIALIST_CONTINUITY`: specialists keep their earlier work within a conversation.

There are no platform token budgets: each person's own key pays for their runs.

## Install the CLI

The `dotrix` command installs on its own (Python 3.11+ and [uv](https://docs.astral.sh/uv/)):

```bash
uv tool install "git+https://github.com/adeyemiadekunle/dotrix#subdirectory=apps/cli"
```

- On Windows, run `uv tool update-shell` once (then open a new terminal) so `dotrix` is on your
  PATH. A standalone Windows CLI is attached to each release.
- Without uv: `pipx install "git+https://github.com/adeyemiadekunle/dotrix#subdirectory=apps/cli"`.
- Point it at your server with `DOTRIX_API_URL` (or `--api-url` on `login`). The default is
  `http://127.0.0.1:8000`.
- Upgrade with `uv tool upgrade dotrix`; remove with `uv tool uninstall dotrix`.

## The CLI with the platform

```bash
dotrix login                                   # device login; the token goes to your OS keychain
cd ~/code/kunemi && dotrix connect             # link this checkout to its project (found by the git remote)
dotrix pull                                    # refresh the .dotrix/ mirror (only what changed)
dotrix chat --mode plan --approvals manual     # talk to the team; /mode, /approvals, /continue; Ctrl+C stops a reply
dotrix brief                                   # a summary of what changed (read-only)
dotrix triage "Drivers see the wrong zone"     # Nova triages a report into an issue (waits for approval)
dotrix review KUN-12                           # Juno checks an issue against its acceptance criteria
dotrix issue list --mine                       # your issues (or --as claude-code for an agent's)
dotrix code KUN-42 --cloud --wait              # ask Kai to code an issue (on your computer without --cloud)
dotrix codes                                   # Kai's sessions; show, follow, approve, accept, stop, revert, recover
dotrix runner                                  # code your local turns on this computer
dotrix handoff install --register              # Claude Code / Codex via MCP: board, documents, graph
dotrix logout
```

**Local turns** (`dotrix runner`, or a folder picked in the desktop app) each run in a git
worktree of their own under `~/.dotrix/worktrees`, so your working copy is never touched. They
use the coding tool signed in on your computer; the platform never sends a key.
- **With [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/) (`sbx`) installed:** each
  turn runs in a microVM of its own and Kai can run tests and commands there. Its key comes
  from `sbx secret set`.
- **Without it:** the tool only edits files.
- Worktrees untouched for 3 days are removed.
- `--isolation auto|sbx|none` chooses.

**Setting a project up.** Owners and admins set a project up once, on the web or with the CLI:
create it (`dotrix connect`, or `dotrix init` for a new repo), add its documents
(`dotrix docs-add <files>`), and have Orion draft its overview (`dotrix architecture draft`).
Everyone else runs `dotrix connect` in their own checkout: it links to the project by the git
remote and changes nothing.

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

## Branches and releases

Branch from `stage` and open pull requests into `stage`; every PR adds a line to
[CHANGELOG.md](CHANGELOG.md) under Unreleased. Merging `stage` into `main` is a release: it tags
the version and publishes the GitHub release, with the desktop installer and the Windows CLI.
Details in [CLAUDE.md](CLAUDE.md#branches-and-releases).

## Checks

CI runs all of these:

```bash
uv run ruff check apps packages && uv run pytest   # lint; unit and integration tests (need Postgres)
pnpm lint && pnpm format:check                     # ESLint and Prettier
pnpm build && pnpm typecheck
pnpm test                                          # web unit tests (Vitest)
pnpm knip                                          # unused files, exports and dependencies
pnpm --filter @dotrix/web e2e                      # browser tests on a rule-based model
python scripts/release.py check                    # one version everywhere, with its changelog section
```
