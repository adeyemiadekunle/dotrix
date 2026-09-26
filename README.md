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
cp .env.example .env     # then set a model API key
```

Run things:

```bash
docker compose -f infra/docker-compose.yml up -d   # Postgres + Redis
pnpm dev:backend         # API on http://localhost:8000 (docs at /docs)
pnpm dev:web             # web on http://localhost:3000
pnpm dev:desktop         # Electron window pointed at the web app
uv run pmagent --help    # CLI
```

Checks:

```bash
uv run pytest && uv run ruff check apps packages
pnpm build && pnpm typecheck
```
