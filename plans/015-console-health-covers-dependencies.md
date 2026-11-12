# Plan 015: The console's health shows the services, workers, backlogs and capacity dotrix depends on

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/backend/src/dotrix_backend/modules/admin apps/backend/src/dotrix_backend/core/storage.py apps/backend/src/dotrix_backend/main.py apps/admin/src`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition. (Earlier plans in this series change
> some of the same files; where "Depends on" names a plan, its changes are
> expected.)

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (read-only additions)
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

The console's Overview answers "is dotrix working" from the database alone: its response time, the run queue, and when a worker last took a run. A deployment can look green while Redis is down, file storage refuses uploads, no worker is alive, notification emails are piling up unsent, or every coding slot is taken. An operator finds out from a user. After this plan the health check covers each dependency with its own state, and the Overview shows them as cards with the same good / watch / attention tones it uses today.

## Current state

The console's data comes from `apps/backend/src/dotrix_backend/modules/admin/platform.py` (`PlatformObserve`: `health`, `counts`, `trends`, `failures`, `coding`, `workspaces`, `audit`), exposed read-only by `modules/admin/router.py` under `/v1/admin/observe/*` and `/v1/admin/audit`, with response models in `modules/admin/schemas.py`. Every route takes `admin: AdminDep`. The console's pages are in `apps/admin/src/pages.tsx` (Overview, Runs, Failures, Coding, Workspaces, Audit), its response types in `apps/admin/src/api.ts`, charts in `charts.tsx`, tables in `table.tsx`. Pages poll with TanStack Query (`refetchInterval`, 15 s for health, 60 s for the rest). Tests: `apps/backend/tests/integration/test_admin.py` builds runs directly with `_chat_run` / `_coding_run` from `tests/integration/test_observe.py`.

`PlatformObserve.health` today (start of the method):

```python
    async def health(self, version: str) -> PlatformHealth:
        """Is the deployment working: the database, the run queue, workers, leases, sandboxes."""
        now = datetime.now(UTC)
        day = now - timedelta(days=1)
        started = time.perf_counter()
        await self.session.execute(text("SELECT 1"))
        database_ms = round((time.perf_counter() - started) * 1000, 1)

        open_dispatch = (RunDispatch.accepted_at.is_(None), RunDispatch.discarded_at.is_(None))
        oldest = await self.session.scalar(select(func.min(RunDispatch.created_at)).where(*open_dispatch))
        last_taken = await self.session.scalar(select(func.max(RunDispatch.accepted_at)))
```

and its route:

```python
@router.get("/observe/health", responses=errors(422))
async def observe_health(admin: AdminDep, request: Request, platform: Platform) -> PlatformHealth:
    return await platform.health(request.app.version)
```

What the app holds, for the new checks:

- **Redis**: the API creates a pool only when `settings.jobs == "worker"` or `settings.rate_limits == "redis"` (`main.py` lifespan, a local variable `redis`; it is not stored on `app.state`). In worker mode `app.state.jobs` is a `QueuedJobs` and `app.state.runner.queue` a `RunQueue`, both holding that pool (`RunQueue.redis`).
- **Workers**: `worker.py` is an arq worker. arq writes a health-check key to Redis on an interval (read arq's `Worker` source in `.venv` for `health_check_key` / `health_check_interval`, and confirm the key name for this project's `queue_name` before relying on it).
- **Storage**: `app.state.storage` is a `BlobStorage | None` (`core/storage.py`; `S3BlobStorage` has `_client()` and `_ensure_bucket`; `MemoryBlobStorage` in tests). There is no cheap "ping" method yet.
- **Email**: `settings.email_backend` is `console` or `sendly`. Unsent notification emails are `Notification` rows with `emailed_at IS NULL` (`modules/notifications/models.py`; an index `ix_notifications_unemailed` exists).
- **Automation events**: the outbox table is `AutomationEventRow` in `modules/automations/models.py` (read it for the column that marks an event handled).
- **GitHub App**: configured when `settings.github_app_id` and a private key are set; the webhook secret is `settings.github_webhook_secret`.
- **Coding capacity**: `settings.coding_max_runs` per worker (0 = no limit); running cloud turns are `CodingRun` rows with `status == RUNNING` and `location == CodingLocation.CLOUD`.
- **Checkouts on disk**: `modules/code/checkouts.py` keeps repos under `settings.code_dir` with `_size(root)` and a cap of `settings.code_max_mb` per repo; they live where agents run (the worker in worker mode), so the API may not see that disk.

The Overview renders health as a list of cards built in `pages.tsx` (`list.map((c) => … className={`hc ${c.tone}`}`), each `{id, label, icon, value, detail, tone}` with tones `good` / `warn` / `bad`, and a banner from the worst tone.

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
- `apps/backend/src/dotrix_backend/core/storage.py` (one `ping` method per storage class)
- `apps/backend/src/dotrix_backend/main.py` (store the Redis pool on `app.state.redis`: one line)
- `apps/backend/tests/integration/test_admin.py` (add tests), `apps/backend/tests/unit/test_storage.py` only if it exists
- `apps/admin/src/api.ts`, `apps/admin/src/pages.tsx`
- `packages/api-client/*` (via `pnpm openapi`), `CHANGELOG.md`

**Out of scope** (do NOT touch):

- Alerting (plan 016). This plan only shows state.
- API error rate and latency: that needs request metrics the app doesn't keep; listed under Maintenance.
- Checkout disk usage when the API can't see the worker's disk: show it only where readable, never guess.
- Changing what `/health` and `/health/ready` (the public liveness routes in `api/health.py`) return.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/015-console-health-covers-dependencies origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: A check type, and the checks

In `schemas.py` add:

```python
class DependencyCheck(BaseModel):
    """One thing dotrix depends on, as the console shows it."""

    id: str = Field(description="redis, storage, email, github, workers")
    state: Literal["ok", "degraded", "down", "off"] = Field(description="off: not configured here, which is allowed")
    detail: str = Field(description="One short line for an operator: never a secret, never text people wrote")
    latency_ms: float | None = None
```

and to `PlatformHealth`: `dependencies: list[DependencyCheck] = []`, `workers_alive: int | None = None` (None: not in worker mode or not knowable), `notification_emails_waiting: int = 0`, `notification_email_oldest_seconds: float | None = None`, `automation_events_waiting: int = 0`, `coding_slots: int | None = None` (the configured limit; None when 0 = no limit), `coding_running_cloud: int = 0`.

In `platform.py` add `async def dependencies(self, app_state) -> list[DependencyCheck]` and call it from the route (pass `request.app.state`); each check is wrapped in `asyncio.wait_for(..., timeout=2)` and its own `try/except Exception` so one failing dependency never fails the health route, and reports `down` with the exception's class name only (never its message, which can carry hostnames or credentials):

- **redis**: `off` when `app.state.redis` is None; else time a `PING`.
- **workers**: only in worker mode. Use arq's health-check key as found in Step 0 below; `down` when the key is missing or stale, `ok` with "a worker checked in N s ago". If the key can't be determined reliably, fall back to `worker_last_took_at` and set state `degraded` with detail "can't confirm a worker is alive".
- **storage**: `off` when `app.state.storage` is None; else call a new `async def ping(self) -> None` (add it to the `BlobStorage` protocol, `S3BlobStorage`: a `head_bucket` on the configured bucket through the same client the class already uses; `MemoryBlobStorage`: returns).
- **email**: `ok` "Sendly" or `degraded` "console (emails are only logged)" from `settings.email_backend`; no network call.
- **github**: `off` when no app id; `degraded` when the app is configured but `github_webhook_secret` is unset ("webhooks can't be verified"); else `ok`. No network call.

Step 0, before writing the workers check: read arq's worker source under `.venv/lib/python*/site-packages/arq/worker.py` for how and where it records its health check, and state in your report the exact key and interval you relied on.

### Step 2: Backlogs and capacity

Still in `health`: count `Notification` rows with `emailed_at IS NULL` older than 5 minutes and the oldest one's age; count unhandled automation events (the column you found in `AutomationEventRow`); set `coding_slots` from `settings.coding_max_runs or None` and `coding_running_cloud` from the `CodingRun` count described above.

Note for the notifications count: a person who chose a daily digest or no email also leaves `emailed_at` empty until their digest. Read `modules/notifications/emails.py` `send_due` to see exactly which rows the minute job is expected to handle, and count only those; if that can't be expressed in one query, count rows older than 24 hours instead and say so in the field's description.

### Step 3: `app.state.redis`

In `main.py`'s lifespan, right after the pool is created (or left `None`), set `app.state.redis = redis`. Initialise `app.state.redis = None` next to the other `app.state` defaults in `create_app` so tests that skip the lifespan still have the attribute.

### Step 4: Tests

In `tests/integration/test_admin.py` add: the health response includes one entry per dependency id; with nothing configured (the test app) redis and storage report `off` or `ok` as the fixtures provide, never a 500; a storage whose `ping` raises reports `down` and the route still answers 200 (monkeypatch `MemoryBlobStorage.ping`); the detail of a failing check contains the exception class name and not its message; `notification_emails_waiting` counts an old unsent immediate notification and not a fresh one; `coding_slots` mirrors the setting.

**Verify**: `uv run pytest apps/backend/tests/integration/test_admin.py apps/backend/tests/unit/test_openapi.py -q` → all pass

### Step 5: The console

`pnpm openapi`. In `api.ts` extend `Health`. In `pages.tsx` add cards to the Overview's list, mapped to tones (`ok` → good, `degraded` → warn, `down` → bad, `off` → good with detail "not configured"): Redis, Workers, Storage, Email, GitHub, "Emails waiting" (warn above 0 for 15 minutes, bad above an hour), "Automation events waiting", and "Coding slots" (`coding_running_cloud` of `coding_slots`; warn when full). Reuse the existing card markup and icons from `@phosphor-icons/react` already imported in the file.

### Step 6: Changelog

Unreleased → Added: `- The admin console's health now covers Redis, workers, file storage, email, the GitHub App, waiting emails and automation events, and coding capacity.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- New tests in `tests/integration/test_admin.py` (Step 4), next to the existing health assertions.

## Done criteria

- [ ] `uv run pytest apps/backend/tests/integration/test_admin.py apps/backend/tests/unit/test_openapi.py -q` exits 0
- [ ] `uv run python apps/backend/scripts/export_openapi.py && git diff --exit-code packages/api-client/openapi.json` exits 0
- [ ] A forced failure of one check (the storage test) leaves `GET /v1/admin/observe/health` at 200
- [ ] `uv run ruff check apps packages` exits 0, and the TS checks exit 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- The storage client in `S3BlobStorage` has no bucket-level read you can call without new permissions — report what it offers instead of adding a write.
- The column marking an automation event as handled can't be identified from `modules/automations`.
- A check would need a paid or rate-limited external call (GitHub, the email provider): keep those checks configuration-only.

## Maintenance notes

- Deferred: API error rate and latency (needs request metrics; the access log in `core/middleware.py` is the place to start), checkout disk usage from the worker (needs the worker to report it), and a live GitHub webhook delivery check.
- Plan 016 (alerts) reads the same `health()`; keep field names stable.
- A reviewer should check no check's `detail` can carry a hostname with credentials or text people wrote.
