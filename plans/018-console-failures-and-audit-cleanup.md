# Plan 018: The console's failure report can't show what people wrote, and the audit log can be filtered

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/backend/src/dotrix_backend/modules/admin apps/admin/src`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition. (Earlier plans in this series change
> some of the same files; where "Depends on" names a plan, its changes are
> expected.)

## Status

- **Priority**: P2
- **Effort**: S–M
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

The console promises to show how the platform is doing, "never what people wrote". Its Failures page breaks that promise by construction: it groups failures by the first 160 characters of each run's recorded error, and a recorded error is whatever the exception said, which for a provider's refusal can echo part of the request. Separately, the audit page can only filter by action, so finding what happened in one workspace or on one day means paging through everything. After this plan the failure report shows a cleaned, classified message, and the audit page filters by workspace, kind of actor and date.

## Current state

The console's data comes from `apps/backend/src/dotrix_backend/modules/admin/platform.py` (`PlatformObserve`: `health`, `counts`, `trends`, `failures`, `coding`, `workspaces`, `audit`), exposed read-only by `modules/admin/router.py` under `/v1/admin/observe/*` and `/v1/admin/audit`, with response models in `modules/admin/schemas.py`. Every route takes `admin: AdminDep`. The console's pages are in `apps/admin/src/pages.tsx` (Overview, Runs, Failures, Coding, Workspaces, Audit), its response types in `apps/admin/src/api.ts`, charts in `charts.tsx`, tables in `table.tsx`. Pages poll with TanStack Query (`refetchInterval`, 15 s for health, 60 s for the rest). Tests: `apps/backend/tests/integration/test_admin.py` builds runs directly with `_chat_run` / `_coding_run` from `tests/integration/test_observe.py`.

How the failure report groups today (`platform.py`):

```python
def _error_line(error: str | None) -> str:
    """The first line of a recorded error, short: enough to group the same failure together."""
    line = (error or "").strip().splitlines()[0] if (error or "").strip() else "(no message)"
    return line[:160]
```

used in `failures()` for both chat (`AgentRun.error`, with `AgentRun.error_kind`) and coding (`CodingRun.error`, with `CodingRun.status`), returning `FailureGroup(key=line, kind=..., detail=..., count, last_at)`. Chat errors are recorded in `modules/agents/runner.py` as `f"{exc.__class__.__name__}: {exc}"` (search for `error=` and `_fail(` there); coding errors are written by `modules/coding/runner.py` and read like "Kai didn't finish: …".

The audit query today:

```python
    async def audit(self, *, action: str | None = None, offset: int = 0, limit: int = 100) -> AuditPage:
        where = []
        if action:
            escaped = action.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append(AuditEvent.action.like(f"{escaped}%", escape="\\"))
        rows = await self.session.execute(
            select(AuditEvent, Workspace.slug)
            .outerjoin(Workspace, Workspace.id == AuditEvent.workspace_id)
            .where(*where)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .offset(offset).limit(limit)
        )
```

(read the live code for the exact escaping; the excerpt above is abbreviated). `PlatformAuditEvent` returns `id`, `action`, `workspace` (slug), `actor_type`, `actor_user_id`, `agent`, `created_at` and deliberately no `details` or `target`. The page is `AuditPage` in `apps/admin/src/pages.tsx`, with one action filter.

Repo conventions that apply (from the repository's `CLAUDE.md`):

- Backend layering is router → service; routers never query. Raise domain exceptions from `dotrix_backend.core.errors`, never `HTTPException`.
- Pydantic v2 schemas are separate from ORM models; never return ORM objects.
- Every schema change is one Alembic migration in `apps/backend/migrations/versions/` (`YYYYMMDD_HHMM_<12 hex>_<slug>.py`, `revision`, `down_revision` = the current head from `uv run --directory apps/backend alembic heads`, working `upgrade()` and `downgrade()`). CI runs `alembic check`.
- Every route has a docstring and `responses=errors(...)`; route function names are the OpenAPI operation IDs. After any API change run `pnpm openapi` and commit `packages/api-client/openapi.json` and `src/schema.ts`.
- Never log a token, password or secret. Secrets at rest are encrypted with `core/crypto.py` `Secrets` (Fernet, `DOTRIX_ENCRYPTION_KEY`).
- The admin console must never show what people wrote (conversation text, document text, audit `details`, raw provider messages).
- UI copy is sentence case. The admin console calls the API only through `apps/admin/src/api.ts`; its pages are in `apps/admin/src/pages.tsx`, its types in `api.ts`, its styles in `admin.css`.
- Every PR adds a line under `## [Unreleased]` in `CHANGELOG.md`, in the existing section of the right kind.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync && pnpm install` | exit 0 |
| Local services (tests need Postgres and Redis) | `pnpm db:up` | containers running |
| Admin tests | `uv run pytest apps/backend/tests/integration/test_admin.py -q` | all pass |
| OpenAPI docs rules | `uv run pytest apps/backend/tests/unit/test_openapi.py -q` | all pass |
| Migrations match models | `uv run --directory apps/backend alembic upgrade head && uv run --directory apps/backend alembic check` | "No new upgrade operations detected" |
| Python lint | `uv run ruff check apps packages` | exit 0 |
| Regenerate API schema + client | `pnpm openapi` | exit 0 |
| TS checks | `pnpm typecheck && pnpm exec eslint . && pnpm format:check && pnpm --filter @dotrix/admin build` | exit 0 |
| Release check | `python scripts/release.py check` | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `apps/backend/src/dotrix_backend/modules/admin/platform.py`, `schemas.py`, `router.py`
- `apps/backend/tests/integration/test_admin.py` (add tests), `apps/backend/tests/unit/test_admin_errors.py` (create)
- `apps/admin/src/api.ts`, `apps/admin/src/pages.tsx`
- `packages/api-client/*` (via `pnpm openapi`), `CHANGELOG.md`

**Out of scope** (do NOT touch):

- How runs record their errors (`modules/agents/runner.py`, `modules/coding/runner.py`): the person who ran it still sees the full error in their own workspace.
- Returning audit `details` or `target` to the console.
- Exporting the audit log.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/018-console-failures-and-audit-cleanup origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: A cleaned failure key

In `platform.py` replace `_error_line` with `def _failure_key(error: str | None) -> str` (keep the old name as a thin alias only if something else imports it; `grep -rn "_error_line" apps/backend` first):

1. Take the first line, as today.
2. If it starts with an exception class name followed by `:` (`^[A-Za-z_][A-Za-z0-9_.]*(Error|Exception|Timeout|Refused|Limit)\w*:`), keep the class name and classify the rest instead of showing it.
3. Classify by pattern into a small fixed vocabulary, checked in order: an HTTP status (`\b(4\d\d|5\d\d)\b`) → "HTTP 429" etc.; rate or quota words → "rate limited"; "timeout" / "timed out" → "timed out"; "connect" / "connection" / "network" / "dns" → "connection failed"; "auth" / "api key" / "unauthorized" / "permission" → "authentication failed"; "context" with "length" or "window" / "too many tokens" → "context too long"; otherwise "other".
4. The key is `"<ClassName>: <classification>"`, or just the classification when there is no class name. For messages the platform itself wrote (they start with one of a short allowlist of prefixes you collect from `modules/coding/runner.py` and `modules/agents/runner.py`, such as "Kai didn't finish", "Stopped by", "The person who asked no longer sees this project"), keep the platform's own prefix up to the first `:` and drop what follows.
5. Never include: anything after the first `:` of an unclassified message, quoted strings, URLs, email addresses, or more than 80 characters.

"Stopped by <name>" must become "Stopped by a person": the name is personal data the console doesn't need.

### Step 2: Tests for the key

`tests/unit/test_admin_errors.py`, table-style: a provider error echoing a prompt (`'BadRequestError: Error code: 400 - {"error": {"message": "…my secret plan…"}}'`) → `"BadRequestError: HTTP 400"` and the secret text absent; a rate limit; a timeout; a connection error; "Stopped by Ada Lovelace" → no name; a platform message keeps its prefix only; `None` and empty → `"(no message)"`; a 500-character single line → at most 80 characters; a message with an email address and a URL → neither appears. In `tests/integration/test_admin.py` extend the failures test: seed a failed chat run whose `error` contains a distinctive sentence and assert the sentence is absent from the whole `/observe/failures` response while the run is still counted.

**Verify**: `uv run pytest apps/backend/tests/unit/test_admin_errors.py apps/backend/tests/integration/test_admin.py -q` → all pass

### Step 3: Audit filters

`PlatformObserve.audit` and `GET /v1/admin/audit` gain optional filters: `workspace` (a slug, exact match on `Workspace.slug`), `actor_type` (`user` / `agent` / `system`, validated against the existing `AuthorType` enum), `since` and `until` (dates, inclusive, UTC days). An unknown slug returns an empty page, not an error. The total reflects the filters. Add tests: each filter narrows the page and the total; combined filters; the response still has no `details` or `target`.

**Verify**: `uv run pytest apps/backend/tests/integration/test_admin.py apps/backend/tests/unit/test_openapi.py -q` → all pass

### Step 4: The console

`pnpm openapi`. On the Failures page nothing changes structurally; relabel the column to "Kind of failure". On the Audit page add, beside the action filter: a workspace field (free text for the slug), an actor select (Anyone / People / Agents / System), and two date inputs; put them in the query key and the request. A row's workspace becomes a button that sets the workspace filter.

### Step 5: Changelog

Unreleased → Security: `- The admin console's failure report shows a kind of failure (for example "HTTP 429" or "timed out") in place of the raw error text, which could repeat part of what someone asked.` Unreleased → Added: `- The admin console's audit log can be filtered by workspace, by who acted and by date.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- New unit file `tests/unit/test_admin_errors.py` (Step 2) and added integration assertions (Steps 2 and 3) in `tests/integration/test_admin.py`.

## Done criteria

- [ ] `uv run pytest apps/backend/tests/unit/test_admin_errors.py apps/backend/tests/integration/test_admin.py apps/backend/tests/unit/test_openapi.py -q` exits 0
- [ ] `uv run python apps/backend/scripts/export_openapi.py && git diff --exit-code packages/api-client/openapi.json` exits 0
- [ ] `grep -n "\[:160\]" apps/backend/src/dotrix_backend/modules/admin/platform.py` returns nothing
- [ ] `uv run ruff check apps packages` exits 0, and the TS checks exit 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- An existing test asserts on a raw error line in the failures response in a way that can't be expressed with the cleaned key — report the test; do not restore raw text.
- You can't tell which message prefixes the platform itself writes: use an empty allowlist (everything classified) and say so.

## Maintenance notes

- The classification vocabulary is deliberately small; add a kind only with a test. Anything unrecognised is "other", which is the safe default.
- If operators need the raw error to debug, the right fix is a per-run view for the workspace's owner, not showing it in the console.
- Plan 016's alert summaries follow the same rule: counts and kinds, never text people wrote.
