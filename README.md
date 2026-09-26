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
