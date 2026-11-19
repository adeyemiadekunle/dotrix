# Plan 016: Operators are emailed when the deployment needs attention

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/backend/src/dotrix_backend/modules/admin apps/backend/src/dotrix_backend/jobs.py apps/backend/src/dotrix_backend/worker.py apps/backend/src/dotrix_backend/main.py apps/admin/src`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition. (Earlier plans in this series change
> some of the same files; where "Depends on" names a plan, its changes are
> expected.)

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (a noisy alert is worse than none)
- **Depends on**: plans/015-console-health-covers-dependencies.md (the states it alerts on). Works without 012, with a configured address list; with 012 it can default to the owners.
- **Category**: dx
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

The admin console only helps while someone is looking at it. Stuck runs, a dead worker, a failed dependency or a spike in failures are found when a user complains. After this plan a job in the worker checks the same health the console shows every few minutes and emails the operators when a condition starts and when it clears — once per condition, not once per check.

## Current state

The console's data comes from `apps/backend/src/dotrix_backend/modules/admin/platform.py` (`PlatformObserve`: `health`, `counts`, `trends`, `failures`, `coding`, `workspaces`, `audit`), exposed read-only by `modules/admin/router.py` under `/v1/admin/observe/*` and `/v1/admin/audit`, with response models in `modules/admin/schemas.py`. Every route takes `admin: AdminDep`. The console's pages are in `apps/admin/src/pages.tsx` (Overview, Runs, Failures, Coding, Workspaces, Audit), its response types in `apps/admin/src/api.ts`, charts in `charts.tsx`, tables in `table.tsx`. Pages poll with TanStack Query (`refetchInterval`, 15 s for health, 60 s for the rest). Tests: `apps/backend/tests/integration/test_admin.py` builds runs directly with `_chat_run` / `_coding_run` from `tests/integration/test_observe.py`.

Scheduled work lives in `apps/backend/src/dotrix_backend/worker.py` (`WorkerSettings.cron_jobs`, e.g. `cron(emails, timeout=2 * 60)` every minute) calling jobs registered in `dotrix_backend/jobs.py` (`JOBS: dict[str, JobFunction]`; a job is `async def name(ctx: JobContext, ...) -> ...`). `JobContext` (`core/jobs.py`) carries `session_factory`, `settings`, `email` (an `EmailSender`; a job sends directly with `await ctx.email.send(EmailMessage(...))`, as `send_email` in `jobs.py` does), and `storage`. In local mode (`settings.jobs == "local"`) `main.py` runs a few jobs on a loop with `_every(local_jobs, name, seconds)`.

`PlatformObserve(session, settings).health(version)` returns `PlatformHealth` (see `modules/admin/schemas.py`): `stuck` (runs whose lease lapsed), `queue_pending`, `queue_oldest_seconds`, `worker_last_took_at`, `recovery_required`, `failed_24h`, `finished_24h`, and after plan 015 `dependencies` (each `state` of `ok` / `degraded` / `down` / `off`), `notification_emails_waiting`, `coding_slots`, `coding_running_cloud`.

Email templates for the app are in `modules/notifications/emails.py` and `core/email.py` (`EmailMessage(to, subject, body, html)`, `text_to_html`). In tests, the `outbox` fixture collects sent messages.

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

- `apps/backend/src/dotrix_backend/core/settings.py` (two settings)
- `apps/backend/src/dotrix_backend/modules/admin/alerts.py` (create), `modules/admin/models.py` (one table)
- `apps/backend/migrations/versions/<new>.py` (create)
- `apps/backend/src/dotrix_backend/jobs.py`, `worker.py`, and `main.py` (register the job; one `_every` line for local mode)
- `apps/backend/tests/integration/test_admin_alerts.py` (create)
- `apps/backend/src/dotrix_backend/modules/admin/schemas.py`, `router.py`, `apps/admin/src/api.ts`, `pages.tsx` (show open alerts on the Overview)
- `.env.example`, `deploy/dokploy.env.example`, `deploy/docker-compose.dokploy.yml`, `deploy/README.md`, `packages/api-client/*` (via `pnpm openapi`), `CHANGELOG.md`

**Out of scope** (do NOT touch):

- Slack, webhooks, SMS or paging services: email only in this plan (a webhook is the natural next step; see Maintenance).
- Per-workspace alerts or anything sent to app users.
- New health checks: alert only on what `health()` already returns.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/016-operator-alerts origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Settings

`core/settings.py`: `alert_emails: list[str] = []` (who gets operator alerts; empty: none are sent, unless plan 012 landed, in which case the default is the active owners' emails) and `alert_interval_minutes: int = Field(default=5, ge=1, le=60)`. Document both in `.env.example` and the deploy files.

### Step 2: Conditions, with state

`AdminAlert` in `models.py`, table `admin_alerts`: `id`, `key` (`String(64)`, unique among open alerts: a partial unique index on `key WHERE resolved_at IS NULL`), `summary` (`String(300)`), `opened_at`, `last_seen_at`, `resolved_at` (nullable), `notified_at` (nullable). Migration with downgrade.

`modules/admin/alerts.py`:

- `def conditions(health: PlatformHealth, now) -> dict[str, str]` — a pure function returning `{key: summary}` for every condition that holds now. Start with exactly these, each a constant at the top of the file:
  - `dependency:<id>` — a dependency's state is `down` ("Redis is down").
  - `workers` — worker mode and no worker confirmed alive.
  - `stuck_runs` — any run in `health.stuck` whose lease lapsed more than 10 minutes ago (the sweep should have recovered it within about two).
  - `queue_stalled` — `queue_pending > 0` and `queue_oldest_seconds > 600`.
  - `recovery_required` — `recovery_required > 0` for coding turns.
  - `failure_rate` — at least 10 runs finished in 24 hours and more than half failed.
  - `emails_waiting` — `notification_emails_waiting > 0` with the oldest more than an hour old.
  Summaries are short sentences with counts only: never a workspace's name, an error message, or anything people wrote.
- `async def evaluate(ctx: JobContext, version: str) -> dict[str, int]` — computes health, compares `conditions(...)` with the open rows: a new key opens a row; a key still present updates `last_seen_at`; an open row whose key is gone gets `resolved_at`. Then sends **one** email per run listing what opened and what cleared (nothing changed: no email), sets `notified_at`, commits. A condition must hold on two consecutive evaluations before it is emailed (open the row on the first, email on the second) so a blip doesn't page anyone. Recipients: `settings.alert_emails`, else active owner admins if `AdminUser.role` exists, else nobody.

### Step 3: Schedule it

Register `check_operator_alerts` in `jobs.py` `JOBS`; in `worker.py` add a cron entry in the style of `emails` that runs every `alert_interval_minutes` (arq's `cron(minute=set(range(0, 60, n)))`; the setting is read in `startup`, so if cron entries can't depend on settings at class-definition time, run it every 5 minutes and have the job skip when `now.minute % interval != 0`). In `main.py`, for local mode add the matching `_every(local_jobs, "check_operator_alerts", 300)` next to the existing loops.

### Step 4: Show open alerts

`GET /v1/admin/observe/alerts` → open alerts and those resolved in the last 24 hours (key, summary, opened, resolved). On the Overview, above the health cards, list open alerts in the existing banner style; nothing when there are none.

### Step 5: Tests

`tests/integration/test_admin_alerts.py`: unit-test `conditions` with hand-built `PlatformHealth` objects for each condition and for a healthy deployment (empty dict); then with the database: a condition present on one evaluation opens a row and sends nothing; on the second it sends one email to `alert_emails`; on a third with no change it sends nothing; when it clears, one "cleared" email and `resolved_at` set; with no recipients nothing is sent and nothing fails; the email body contains counts and no workspace names (seed a workspace with a distinctive name and assert it is absent). Use the `outbox` fixture; build a `JobContext` the way an existing job test does (`grep -rn "JobContext(" apps/backend/tests | head`).

**Verify**: `uv run pytest apps/backend/tests/integration/test_admin_alerts.py apps/backend/tests/integration/test_admin.py -q` → all pass; the migrations command → no new operations

### Step 6: Docs and changelog

`deploy/README.md`: set `DOTRIX_ALERT_EMAILS` to get alerts; what triggers one. CHANGELOG → Added: `- Operators can be emailed when dotrix needs attention (a service down, no worker, stuck or failing runs) and again when it clears.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- New file `tests/integration/test_admin_alerts.py` (Step 5). `conditions` is pure and gets table-style tests.

## Done criteria

- [ ] `uv run pytest apps/backend/tests/integration/test_admin_alerts.py apps/backend/tests/integration/test_admin.py -q` exits 0
- [ ] The migrations command reports no new operations
- [ ] `uv run python apps/backend/scripts/export_openapi.py && git diff --exit-code packages/api-client/openapi.json` exits 0
- [ ] A healthy test deployment produces zero alerts and zero emails
- [ ] `uv run ruff check apps packages` exits 0, and the TS checks exit 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- Plan 015 has not landed: implement only the conditions whose inputs exist in `PlatformHealth` on your base (stuck runs, queue stalled, recovery required, failure rate) and say which were left out.
- The job would have to run inside the API in worker mode to work (it must run in the worker).
- A threshold in Step 2 fires on the test suite's ordinary data — report it; do not loosen it silently.

## Maintenance notes

- Thresholds are constants at the top of `alerts.py`; tune them there after watching real traffic.
- Next step: a webhook URL setting posting the same summary (Slack-compatible), and alerting on repeated failed admin sign-ins from plan 014's table.
- A reviewer should check the two-evaluation rule, that summaries carry no names or error text, and that an email provider outage can't make the job fail in a loop (catch the send error, keep `notified_at` empty, try next time).
