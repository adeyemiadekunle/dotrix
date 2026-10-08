# pmagent 

# Now dotrix
Dotrix — The AI workspace for building software.

"Dotrix is inspired by linear algebra — dots represent specialised components, while the matrix represents the relationships between them. Dotrix brings AI agents, knowledge, tasks and tools together into one coordinated workspace"

An AI project team for software projects. Agents write and maintain a project's documents and
board, people approve every change, and Claude Code or Codex do the coding.

- **A team of agents you configure:**
  - The Project Manager and five specialists: Product, Architecture, Research, Reviewer, and
    Documentation.
  - Owners and admins can edit any of them, or create their own: instructions, model, tools,
    folder access, autonomy rules, budgets.
- **One source of truth per project:** a versioned `.pmagent/` knowledge store (requirements,
  architecture, decisions, research), a Jira-style board, and a project graph that links them.
- **Approvals, always:** no agent changes anything without an approval. Either a person
  approves it at the time, or an owner has allowed one low-risk action (a comment or a link).
  Every change is in the audit log.
- **Agents that work in the background:** automations run on a schedule or when people change
  things. Examples: "Keep documents current" after approved changes, a weekly status, triage of
  new issues, a watch on a topic.
- **Agents that learn:**
  - Rules set for the whole workspace, layered under each project's own.
  - Skills (procedures agents follow) and folder templates.
  - Lessons proposed from rejected changes and dismissed results, which owners accept or
    decline.

Product spec: [docs/prd.md](docs/prd.md). The agents' design: [docs/agents-v2.md](docs/agents-v2.md).
The plan and what's built, item by item: [CLAUDE.md](CLAUDE.md).

## What you can do today

- **Chat** with the project's agents, in one Chat for the workspace:
  - Pick who answers (Auto brings in the specialists it needs) and the model.
  - Follow what each agent is doing as it works.
  - Approve or reject each change, with diffs.
  - Ask across several projects at once; those conversations are read-only.
- **Plan and track:**
  - Board, List, Table, and Timeline (dependencies, drag to reschedule) for each project.
  - My issues, Tasks, an Overview, and Activity across the workspace.
  - ⌘K search over issues, documents, projects, people, and agents.
- **Keep knowledge current:**
  - Documents with full history, restore, and export.
  - Uploads converted to Markdown.
  - Hybrid search (keywords and meaning, with pgvector).
  - The project graph, which shows what relates to what, what a change affects, and which
    documents may be out of date. It's drawn in Knowledge.
- **Research** on the web (Tavily): every claim is checked against the page it cites, and
  reports can be saved as research notes.
- **Code awareness:** connect a repo through the pmagent GitHub App and agents read its code
  (read-only) when reviewing or planning.
- **Coding:** "Start coding" on an issue hands it to Claude Code (or Codex, when the server has
  only an OpenAI key).
  - It runs headless in a sandbox (OpenShell), from a brief: the issue, its acceptance
    criteria, and the documents it links to.
  - Each run waits for an approval. You can follow it as it works, and stop it.
  - The platform pushes a new branch and opens the PR. The issue moves to review, and the
    Reviewer reads the PR.
  - Guardrails: the agent never holds a GitHub token, and nothing is pushed to the default
    branch. Changes to `.pmagent/` or CI workflows are refused, and a person merges.
  - Setup: [infra/coding/README.md](infra/coding/README.md).
- **Notifications:**
  - What happens: approvals waiting, decisions, mentions, assignments, findings, and changes to
    issues you watch.
  - Where: in the app and by email, as it happens, as a daily digest, or off.
- **Teams:**
  - Personal workspaces and organisations, with roles and invites.
  - Restricted projects.
  - Sign-in with a password, an email link, or GitHub.
  - Sessions per device.
- **CLI and MCP:** `pmagent` chats, briefs, triages, reviews, and works the board from a
  terminal. Its MCP server gives Claude Code and Codex the board, the documents, and the graph.

## What's next

- **Coding, next:**
  - Coding from the CLI or desktop, in your own checkout.
  - PR events back on the board.
  - The board and documents available to the coding agent inside its sandbox.
- **Background commit review:** a code graph and the blast radius of each push.
- **Space:** workspace-level knowledge, and ideas before a project exists.
- **To do for whoever runs it:**
  - Register the GitHub App.
  - Verify a sending domain for email.
  - Production: a domain, HTTPS, and a secrets store.

## Monorepo layout

```
apps/
  backend/      FastAPI platform API: accounts, workspaces, projects, knowledge, issues, agents,
                approvals, automations, notifications, the graph, connectors (Python)
  cli/          `pmagent` terminal client + MCP server for Claude Code / Codex (Python)
  web/          Web app (Vite + React)
  desktop/      Desktop shell around the web app (Electron)
packages/
  engine/       UI-agnostic agent engine: agent contracts, pipelines, approvals, tools (Python)
  api-client/   Typed client for the backend API, generated from its OpenAPI schema
  ui/           shadcn/ui components, the chat kit, and the theme
infra/          Local services: Postgres with pgvector, Redis, MinIO
docs/           The PRD, the engine, and the agents v2 spec
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
pnpm dev:worker          # only with PMAGENT_JOBS=worker: agent runs and jobs survive API restarts
pnpm dev:web             # web on http://localhost:3000
pnpm dev:desktop         # Electron window on the web app
uv run pmagent --help    # CLI
```

**Configuration** (all in `.env`, explained in [.env.example](.env.example)):
- **Required:** a model key (Anthropic, OpenAI, or Google) and `PMAGENT_DEFAULT_MODEL`.
- **Optional:**
  - `PMAGENT_EMBEDDING_MODEL`: search by meaning; without it, search uses keywords only.
  - `PMAGENT_TAVILY_API_KEY`: web research through Tavily.
  - `PMAGENT_SENDLY_API_KEY`: real email delivery.
  - The GitHub sign-in and GitHub App settings: sign-in with GitHub and connected repos.
  - `PMAGENT_CODING_SANDBOX`: coding runs (`openshell`, or `local` for development only).
- **Limits:**
  - `PMAGENT_RUN_TOKEN_BUDGET`: tokens per agent run.
  - `PMAGENT_AUTOMATION_DAILY_RUNS` and `PMAGENT_AUTOMATION_DAILY_TOKENS`: automation runs and
    tokens per workspace per day.

## Install the CLI

The `pmagent` command installs on its own (Python 3.11+ and [uv](https://docs.astral.sh/uv/)):

```bash
uv tool install "git+https://github.com/adeyemiadekunle/multi-agent-pm#subdirectory=apps/cli"
```

- On Windows, run `uv tool update-shell` once (then open a new terminal) so `pmagent` is on your PATH.
- Without uv: `pipx install "git+https://github.com/adeyemiadekunle/multi-agent-pm#subdirectory=apps/cli"`.
- Point it at your server with `PMAGENT_API_URL` (or `--api-url` on `login`). The default is
  `http://127.0.0.1:8000` until a hosted platform exists.
- Upgrade with `uv tool upgrade pmagent`; remove with `uv tool uninstall pmagent`.

## The CLI with the platform

```bash
pmagent login                                   # device login; the token goes to your OS keychain
cd ~/code/kunemi && pmagent connect             # link this checkout to its project (found by the git remote)
pmagent pull                                    # refresh the .pmagent/ mirror (only what changed)
pmagent chat --agent research                   # talk to the team; approve or reject each change inline
pmagent brief                                   # a summary of what changed (read-only)
pmagent triage "Drivers see the wrong zone"     # the PM triages a report into an issue (waits for approval)
pmagent review KUN-12                           # the Reviewer checks an issue against its acceptance criteria
pmagent issue list --mine                       # your issues (or --as claude-code for an agent's)
pmagent issue claim KUN-42 --as claude-code     # coding tools act as themselves and stop at review
pmagent issue done KUN-42                       # only a person closes
pmagent handoff install --register              # Claude Code / Codex via MCP: board, documents, graph
pmagent logout
```

**Setting a project up, and working in it.** Owners and admins set a project up once, on the
web or with the CLI:
- Create it (`pmagent connect`, or `pmagent init` for a new repo).
- Add its documents (`pmagent docs-add <files>`).
- Have the Architecture agent draft its overview (`pmagent architecture draft`).

Everyone else just runs `pmagent connect` in their own checkout: it links to the project by the
git remote and changes nothing.

`PMAGENT_TOKEN` overrides the keychain for CI. Unlinked repos keep working with local files
(`--local`, `pmagent task …`).

## API documentation

With the backend running (`pnpm dev:backend`):

- **Swagger UI**: http://localhost:8000/docs. Click **Authorize** and paste an `access_token`
  from `/v1/auth/login` to try routes that need you to be signed in.
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI schema**: http://localhost:8000/openapi.json, also committed at
  [packages/api-client/openapi.json](packages/api-client/openapi.json)

The TypeScript client in `packages/api-client` is generated from that schema. After changing
any route or schema, run `pnpm openapi` and commit the result; CI fails if they're out of date.
Set `PMAGENT_DOCS_ENABLED=false` to turn the docs off.

## Checks

CI runs all of these:

```bash
uv run ruff check apps packages && uv run pytest   # lint; unit and integration tests (need Postgres)
pnpm build && pnpm typecheck
pnpm --filter @pmagent/web e2e                     # browser tests on a rule-based model
```
