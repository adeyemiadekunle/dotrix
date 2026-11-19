# Plan 014: What admins do in the console is recorded and shown

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/backend/src/dotrix_backend/modules/admin apps/admin/src apps/backend/src/dotrix_backend/jobs.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition. (Earlier plans in this series change
> some of the same files; where "Depends on" names a plan, its changes are
> expected.)

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: plans/012-several-admins-invites-and-roles.md (the actions worth recording); plans/013-admin-two-factor-sign-in.md if landed (its events)
- **Category**: security
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

Once several people can sign in to a console that sees every workspace, the deployment needs to know who signed in, who invited or removed whom, and who failed to sign in. Today nothing records any of it: the platform's audit log (`audit_events`) belongs to workspaces and has no place for admin actions. After this plan every admin sign-in, failed sign-in, invite, role change, removal, password change and second-factor change is kept in an append-only table and shown on a page in the console, to owners.

## Current state

The admin console (`apps/admin`) has its own accounts in `apps/backend/src/dotrix_backend/modules/admin`:

- `models.py` — `AdminUser`, `AdminSession` (and, after plan 012, `AdminInvite`, `AdminUser.role` / `disabled_at`).
- `service.py` — `AdminService` (`signup`, `login`, `refresh`, `logout`, `read`, `_tokens`) and the `get_admin` dependency (`AdminDep`), which decodes the `dtx_admin_access` cookie (a JWT with `sub`, `sid`, `type="admin"`) and checks the `AdminSession` row.
- `router.py` — `/v1/admin/login` and friends; cookies are set by `_set_session(response, access, refresh, settings)` (httpOnly, `SameSite=Strict`). Login is rate-limited with `ThrottleDep` from `modules/auth/limits.py`.
- `apps/admin/src/App.tsx` — the `Login` component and the shell.
- Tests: `apps/backend/tests/integration/test_admin.py` (`_admin(db_client)` creates and signs in the first admin).

The workspace audit log for comparison: `modules/audit/models.py` `AuditEvent` (`workspace_id`, `action` `String(64)`, `target`, `actor_type`, `actor_user_id`, `details` JSONB, `created_at`) written through `modules/audit/service.py` `AuditLog`. Admins are not app users and have no workspace, so their trail gets its own table instead of reusing this one.

The console's audit page (`apps/admin/src/pages.tsx` `AuditPage`) shows the platform's audit events through `GET /v1/admin/audit` with paging (`offset`, `limit`, `total`) on the shared `DataTable` in `apps/admin/src/table.tsx`. Use it as the pattern for the new page.

The caller's IP comes from `core/ratelimit.py` `client_ip(request, settings.trusted_proxies)`.

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

- `apps/backend/src/dotrix_backend/modules/admin/models.py`, `schemas.py`, `service.py`, `router.py`, `accounts.py`, a new `modules/admin/trail.py`
- `apps/backend/migrations/versions/<new>.py` (create)
- `apps/backend/src/dotrix_backend/jobs.py` (retention in the existing `cleanup_expired` job only)
- `apps/backend/tests/integration/test_admin_trail.py` (create)
- `apps/admin/src/App.tsx`, `api.ts`, `pages.tsx`
- `packages/api-client/*` (via `pnpm openapi`), `CHANGELOG.md`

**Out of scope** (do NOT touch):

- The workspace audit log (`modules/audit`) and its page.
- Recording which observability pages an admin viewed (reads are not recorded; only sign-ins and changes).
- Sending the trail anywhere (alerts are plan 016).

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/014-admin-trail origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Table and writer

`AdminEvent` in `models.py`, table `admin_events`: `id`, `action` (`String(64)`), `admin_user_id` (FK `admin_users.id`, `ondelete="SET NULL"`, nullable — the actor), `actor_email` (`String(320)`, kept so the row still reads after the account is gone; for a failed sign-in, the email that was tried), `target_email` (`String(320)`, nullable), `ip` (`String(64)`, nullable), `created_at` (indexed). No free-text details column. Migration with downgrade.

`modules/admin/trail.py`: `def record(session, action, *, admin=None, actor_email=None, target_email=None, ip=None) -> None` that adds a row (no commit); and `async def page(session, *, action=None, offset=0, limit=25) -> tuple[list[AdminEvent], int]`.

### Step 2: Record these actions

Call `record` in the same transaction as the change, so an event exists exactly when the change committed. A failed sign-in commits its own row before raising.

| Action | Where |
|---|---|
| `admin.signed_in`, `admin.sign_in_failed` | `AdminService.login` (and `login/verify` if plan 013 landed: `admin.second_factor_failed`) |
| `admin.signed_out` | `logout` |
| `admin.created` | `signup`, invite acceptance, and `accounts.create_admin` when called from the command line (`actor_email="command line"`) |
| `admin.invited`, `admin.invite_revoked` | plan 012's invite routes |
| `admin.role_changed`, `admin.disabled`, `admin.enabled`, `admin.removed` | plan 012's `PATCH` / `DELETE` |
| `admin.password_changed`, `admin.password_reset` | `/me/password`; `accounts.reset_admin_password` |
| `admin.two_factor_enabled`, `admin.two_factor_reset`, `admin.recovery_code_used` | plan 013's routes, if present |

The router passes the caller's IP (`client_ip(request, settings.trusted_proxies)`) down to the service. Never record a password, token, code or the invite link.

### Step 3: Read route, retention, tests

- `GET /v1/admin/trail` (owners only if plan 012's `OwnerDep` exists, else any admin): `action` prefix filter, `offset`, `limit`, returns `{items, total}` shaped like `AuditPage`.
- In `jobs.py` `cleanup_expired`, delete `admin_events` older than 400 days, in the style of the other deletions there, and add its count to the job's returned dict.
- `tests/integration/test_admin_trail.py`: each action in the table that exists on your base produces exactly one row with the right actor and target; a failed sign-in is recorded with the tried email and no account id; the serialised page contains none of the passwords or tokens the test used; the route pages and filters; a viewer gets 403 if roles exist.

**Verify**: `uv run pytest apps/backend/tests/integration -q -k admin` → all pass; the migrations command → no new operations

### Step 4: The console

`pnpm openapi`. Add a page "Admin activity" to `PAGES` (owners only when roles exist), built like `AuditPage` on `DataTable`: when, action (map each action to a short sentence-case label), who, target, IP. An action filter like the audit page's.

### Step 5: Changelog

Unreleased → Added: `- The admin console keeps a record of admin sign-ins and changes to admin accounts, shown to owners.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- New file `tests/integration/test_admin_trail.py` (Step 3), modelled on `tests/integration/test_admin.py`.

## Done criteria

- [ ] `uv run pytest apps/backend/tests/integration -q -k admin` exits 0
- [ ] The migrations command reports no new operations
- [ ] `uv run python apps/backend/scripts/export_openapi.py && git diff --exit-code packages/api-client/openapi.json` exits 0
- [ ] `uv run ruff check apps packages` exits 0, and the TS checks exit 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- Plan 012 has not landed: record only the actions that exist (sign-in, sign-out, sign-up, command-line create and reset) and say so in your report; do not invent the missing routes.
- Recording an event would need a commit inside a function documented as "no commit inside".

## Maintenance notes

- New admin actions added later (console actions on runs or workspaces) must call `trail.record`; a reviewer should ask for it.
- Retention is 400 days; change it in `cleanup_expired`.
- Deferred: exporting the trail; alerting on repeated failed sign-ins (plan 016 can read this table).
