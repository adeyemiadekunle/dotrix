# pmagent

The AI project team for any project: a Project Manager agent, five thinking agents
(Product, Architecture, Research, Reviewer, Documentation), and a coding agent, working
around one structured source of truth (`.pmagent/`) and a Jira-style board.
See [docs/prd.md](docs/prd.md).

## Monorepo layout

```
apps/
  backend/      FastAPI platform API: accounts, workspaces, projects, issues, approvals, sync (Python)
  cli/          `pmagent` terminal client + MCP server for Claude Code / Codex (Python)
  web/          Web app: board, backlog, chat, briefings, approvals (Next.js)
  desktop/      Desktop shell around the web app (Electron)
packages/
  engine/       UI-agnostic agent engine: agents, issues, approvals, jobs, ingestion (Python)
  shared/       Domain types shared by the TS apps (issue types, statuses, roles)
  api-client/   Typed client for the backend API
  ui/           Shared React components for web and desktop
infra/          Local services (Postgres, Redis)
docs/           PRD and engine notes
```

Python is a [uv](https://docs.astral.sh/uv/) workspace; TypeScript is a
[pnpm](https://pnpm.io/) workspace orchestrated by [Turborepo](https://turbo.build/).
Web, desktop, and CLI are all clients of one API; the engine never depends on a UI.

## Getting started

Requirements: Python 3.11+, uv, Node 24+, pnpm 11, Docker (for Postgres/Redis).

```bash
uv sync                  # Python: engine, CLI, backend + dev tools
pnpm install             # TypeScript apps and packages
cp .env.example .env     # then replace every change-me and set a model API key
```

Run things:

```bash
pnpm db:up && pnpm db:migrate   # Postgres, Redis, MinIO (localhost only), apply migrations
pnpm dev:backend         # API on http://localhost:8000 (agents need a model key in .env)
pnpm dev:web             # web on http://localhost:3000
pnpm dev:desktop         # Electron window pointed at the web app
uv run pmagent --help    # CLI
```

## Install the CLI

The `pmagent` command installs on its own (Python 3.11+ and [uv](https://docs.astral.sh/uv/)):

```bash
uv tool install "git+https://github.com/adeyemiadekunle/multi-agent-pm#subdirectory=apps/cli"
```

- On Windows, run `uv tool update-shell` once (then open a new terminal) so `pmagent` is on your PATH.
- Without uv: `pipx install "git+https://github.com/adeyemiadekunle/multi-agent-pm#subdirectory=apps/cli"`.
- Point it at your server with `PMAGENT_API_URL` (or `--api-url` on `login`); the default is
  `http://127.0.0.1:8000` until the hosted platform exists.
- Upgrade with `uv tool upgrade pmagent`; remove with `uv tool uninstall pmagent`.

It includes the local agent engine, so commands also work offline on unlinked repos. Then:
`pmagent login`, `pmagent link . --workspace <slug> --project <KEY>` (see below).

## The CLI with the platform

```bash
pmagent login                                   # device login; token goes to your OS keychain
cd ~/code/kunemi && pmagent connect             # link this checkout to its project (found by the git remote)
pmagent pull                                    # refresh the mirror (only what changed; --force takes platform versions)
pmagent brief                                   # the platform team's daily briefing (read-only)
pmagent chat                                    # talk to the team; approve or reject each change inline (diffs shown)
pmagent issue list --mine                       # your issues (or --as claude-code for an agent's)
pmagent issue claim KUN-42 --as claude-code     # coding tools act as themselves and stop at review
pmagent issue review KUN-42 "What changed" --pr <url> --as claude-code
pmagent issue done KUN-42                       # only a person closes
pmagent handoff install --register              # Claude Code / Codex via MCP; linked repos use the platform board
pmagent logout
```

**Project setup vs. working copies.** Setting a project up is for workspace owners and admins,
once: `pmagent connect` (or `pmagent init` for a new repo) in their checkout creates the project,
then `pmagent docs-add <files>` adds its external docs and `pmagent architecture draft` has the
Architecture agent draft `architecture/overview.md` (a repo summary of file layout, manifests, and
README is shown for approval first; never source code). Everyone else just runs `pmagent connect`
in their own checkout: it links to that project by the git remote and changes nothing on it.
Changes to `architecture/` always need an owner or admin to approve.

`PMAGENT_API_URL` points the CLI at a server (default `http://127.0.0.1:8000`); `PMAGENT_TOKEN`
overrides the keychain for CI. Unlinked repos keep working with local files (`pmagent task …`).

## API documentation

With the backend running (`pnpm dev:backend`):

- **Swagger UI**: http://localhost:8000/docs (click **Authorize** and paste an `access_token` from `/v1/auth/login` to try authenticated routes)
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI schema**: http://localhost:8000/openapi.json, also committed at [packages/api-client/openapi.json](packages/api-client/openapi.json)

The TypeScript client in `packages/api-client` is generated from that schema. After changing
any route or schema, run `pnpm openapi` and commit the result; CI fails if they're out of date.
Set `PMAGENT_DOCS_ENABLED=false` to turn the docs off.

Checks:

```bash
uv run pytest && uv run ruff check apps packages
pnpm build && pnpm typecheck
```
