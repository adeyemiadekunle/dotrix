# Plan 011: Admin accounts can be created and rescued from the server's command line

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/backend/src/dotrix_backend/modules/admin apps/backend/src/dotrix_backend/core/openapi.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

The admin console's first account is created through a public sign-up form guarded by a secret in the server's environment (`DOTRIX_ADMIN_BOOTSTRAP_TOKEN`). That works once. After it there is no way to create another admin, and no way back in if the only admin forgets their password. Whoever can run a command on the server already controls the deployment, so the command line is the right place for both jobs: no secret has to sit in the environment, and nothing is exposed on the network. After this plan an operator can list admins, create one, and reset one's password from the host.

## Current state

The admin console (`apps/admin`, served on its own origin) has its own accounts, separate from app users:

- `apps/backend/src/dotrix_backend/modules/admin/models.py` — `AdminUser` (`email` unique, `name`, `password_hash`, `created_at`, plus two unused leftovers: `workspace_id`, `user_id`) and `AdminSession` (`admin_user_id`, `token_hash`, `created_at`, `last_used_at`, `expires_at`, `revoked_at`).
- `modules/admin/service.py` — `AdminService`: `bootstrap_available()`, `token_required()`, `signup()` (first account only, guarded by `DOTRIX_ADMIN_BOOTSTRAP_TOKEN` and an advisory lock), `login()`, `refresh()`, `logout()`, `read()`; and the `get_admin` dependency (`AdminDep`), which decodes the `dtx_admin_access` cookie, checks the session row and returns the `AdminUser`.
- `modules/admin/router.py` — `/v1/admin/bootstrap`, `/signup`, `/login`, `/refresh`, `/logout`, `/me`, then the read-only observability routes. Every route sits behind `require_admin_header` (non-GET requests need `X-Requested-With`). Cookies are set by `_set_session` (httpOnly, `SameSite=Strict`, `Secure` when deployed).
- `modules/admin/schemas.py` — `AdminSignup`, `AdminLogin`, `AdminRead`, `AdminBootstrap`, and the observability payloads.
- `apps/admin/src/App.tsx` — `Login` (sign-up form while `/admin/bootstrap` says `enabled`), the shell with `PAGES` nav, and lazy pages from `apps/admin/src/pages.tsx`.
- Tests: `apps/backend/tests/integration/test_admin.py` (`_admin(db_client)` signs the first admin up; the `admin_header` autouse fixture sets `X-Requested-With`).

`login` today (`service.py`):

```python
    async def login(self, data: AdminLogin) -> tuple[str, str]:
        admin = await self.session.scalar(select(AdminUser).where(AdminUser.email == data.email.lower()))
        if admin is None or not verify_password(admin.password_hash, data.password):
            raise Unauthorized("Wrong email or password")
        pair = await self._tokens(admin)
        await self.session.commit()
        return pair
```

The end of `get_admin` today:

```python
    admin = await session.get(AdminUser, admin_id)
    if admin is None:
        raise Unauthorized("That admin account is gone")
    return admin
```

The only command-line entry points in the backend are `python -m dotrix_backend.serve` (`serve.py`, `argparse`, a `main()` and `if __name__ == "__main__": main()`) and `python -m dotrix_backend.worker`. Database access outside a request uses `create_engine` / `create_sessionmaker` from `dotrix_backend.db.session` with `get_database_settings().database_url` (see how `apps/backend/migrations/env.py` and `main.py` obtain them). `DatabaseSettings` needs only `DOTRIX_DATABASE_URL`, so the command must not require the full `Settings` (no JWT secret needed).

Stale wording that this plan also fixes: the module docstring of `modules/admin/models.py` (lines 1-5) and the `admin` tag description in `core/openapi.py` still say an admin account is created "by proving ownership of a workspace". That was never implemented.

Repo conventions that apply (from the repository's `CLAUDE.md`):

- Backend layering is router → service; routers never query. Raise domain exceptions from `dotrix_backend.core.errors` (`NotFound`, `Forbidden`, `Conflict`, `Unauthorized`), never `HTTPException`.
- Pydantic v2 schemas are separate from ORM models; never return ORM objects.
- Every schema change is one Alembic migration in `apps/backend/migrations/versions/`, named `YYYYMMDD_HHMM_<12 hex>_<slug>.py`, with `revision`, `down_revision` (the current head: run `uv run --directory apps/backend alembic heads`) and both `upgrade()` and `downgrade()`. CI runs `alembic check`.
- Every route has a docstring and `responses=errors(...)`; route function names are the OpenAPI operation IDs. After any API change run `pnpm openapi` and commit `packages/api-client/openapi.json` and `src/schema.ts`.
- Tokens are stored only as SHA-256 hashes (`core/security.py`: `generate_token`, `hash_token`); passwords with Argon2 (`hash_password`, `verify_password`). Never log a token, password or secret.
- The admin console must never show what people wrote (conversation text, document text, audit `details`).
- UI copy is sentence case. The admin console (`apps/admin`) calls the API only through `call` / `rawCall` in `apps/admin/src/api.ts`.
- Every PR adds a line under `## [Unreleased]` in `CHANGELOG.md`, in the existing section of the right kind (Added, Changed, Fixed, Security).

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
| TS checks | `pnpm typecheck && pnpm exec eslint . && pnpm format:check` | exit 0 |
| Release check | `python scripts/release.py check` | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `apps/backend/src/dotrix_backend/admin_cli.py` (create)
- `apps/backend/src/dotrix_backend/modules/admin/accounts.py` (create: the shared create/reset logic)
- `apps/backend/src/dotrix_backend/modules/admin/models.py` (docstring only)
- `apps/backend/src/dotrix_backend/core/openapi.py` (the `admin` tag's description only)
- `apps/backend/tests/integration/test_admin_cli.py` (create)
- `deploy/README.md`, `packages/api-client/openapi.json`, `packages/api-client/src/schema.ts` (the last two only via `pnpm openapi`), `CHANGELOG.md`

**Out of scope** (do NOT touch):

- `modules/admin/service.py`, `router.py` — the web sign-up and its setup token stay as they are (removing them is a later decision).
- Dropping the unused `AdminUser.workspace_id` / `user_id` columns — plan 012 does the migration.
- Any network-reachable way to create admins — plan 012 (invites).

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/011-admin-accounts-from-the-server origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change (e.g. `Admin console's first sign-up needs a deployment setup token`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: The shared account logic

Create `modules/admin/accounts.py` with three async functions taking an `AsyncSession` (no commit inside; the caller commits):

- `async def create_admin(session, *, email: str, name: str, password: str) -> AdminUser` — lower-cases the email, refuses a duplicate with `Conflict("An admin with this email already exists")`, requires `len(password) >= 12` (raise `Unprocessable` or `ValueError`; pick whichever `core/errors.py` offers and say which in your report), hashes with `hash_password`, sets `created_at=datetime.now(UTC)`.
- `async def reset_admin_password(session, *, email: str, password: str) -> AdminUser` — `NotFound` if there is no such admin; sets the new hash and **revokes every session of that admin** (`update(AdminSession).where(admin_user_id == …, revoked_at.is_(None)).values(revoked_at=now)`).
- `async def list_admins(session) -> list[AdminUser]` — ordered by `created_at`.

**Verify**: `uv run ruff check apps/backend` → exit 0

### Step 2: The command

Create `apps/backend/src/dotrix_backend/admin_cli.py`, modelled on `serve.py` (`argparse`, `main()`, the `__main__` guard), run as `python -m dotrix_backend.admin_cli`:

- `list` — prints one line per admin: email, name, created date. Never prints hashes.
- `create --email E --name N` — reads the password with `getpass.getpass` twice (must match), or from the `DOTRIX_ADMIN_PASSWORD` environment variable when set (for non-interactive use). Never accepts the password as a command-line argument (it would show in the process list and shell history).
- `reset-password --email E` — same password input; prints that the admin's sessions were signed out.

Each subcommand builds an engine from `get_database_settings().database_url`, opens one session, calls the function from Step 1, commits, disposes the engine, and exits 0; a domain error prints its message to stderr and exits 1. Use `asyncio.run`. On Windows keep the selector-loop note from `serve.py` if `serve.py` needs one for database access (read it and mirror what it does).

**Verify**: `uv run python -m dotrix_backend.admin_cli --help` → lists `list`, `create`, `reset-password`

### Step 3: Tests

Create `apps/backend/tests/integration/test_admin_cli.py`. Test the functions from Step 1 against the test database using the `db_session` fixture (see `tests/conftest.py`), and the web login through `db_client`:

1. `create_admin` then `POST /v1/admin/login` with those credentials → 204 and both cookies set.
2. A second `create_admin` with another email works even though an admin already exists (this is the point: the web sign-up would be closed).
3. A duplicate email → `Conflict`; a short password is refused.
4. `reset_admin_password`: the old password stops working (401), the new one works, and a session cookie obtained before the reset is rejected on `GET /v1/admin/me` (401).
5. `list_admins` returns both, oldest first.

Add one test that runs the CLI's argument parser only (`--help` exits 0 via `pytest.raises(SystemExit)`); do not spawn a subprocess against a real database.

**Verify**: `uv run pytest apps/backend/tests/integration/test_admin_cli.py apps/backend/tests/integration/test_admin.py -q` → all pass

### Step 4: Fix the stale wording, document, changelog

- `modules/admin/models.py` docstring: say admin accounts are a separate identity for the admin console, created with the deployment's setup token (first account) or from the server's command line.
- `core/openapi.py`: find the `admin` entry in `TAGS` and correct its description the same way; then run `pnpm openapi`.
- `deploy/README.md`: next to the sentence about `DOTRIX_ADMIN_BOOTSTRAP_TOKEN`, add how to run the command inside the API container (`docker compose exec api python -m dotrix_backend.admin_cli create --email … --name …`) and that `reset-password` is the way back in.
- `CHANGELOG.md` → Unreleased → Added: `- Operators can list admin console accounts, create one and reset one's password from the server's command line (python -m dotrix_backend.admin_cli).`

**Verify**: `grep -rn "proving ownership\|proving you own\|proving they own" apps/backend/src deploy` → no matches; `python scripts/release.py check` → exit 0; `uv run python apps/backend/scripts/export_openapi.py && git diff --exit-code packages/api-client/openapi.json` → exit 0

## Test plan

- New file `tests/integration/test_admin_cli.py` with the six cases in Step 3, modelled on `tests/integration/test_admin.py`.

## Done criteria

- [ ] `uv run pytest apps/backend/tests/integration/test_admin_cli.py apps/backend/tests/integration/test_admin.py apps/backend/tests/unit/test_openapi.py -q` exits 0
- [ ] `uv run ruff check apps packages` exits 0
- [ ] `uv run python -m dotrix_backend.admin_cli --help` exits 0
- [ ] `grep -rn "argv\|--password" apps/backend/src/dotrix_backend/admin_cli.py` shows no password taken from the command line
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- Importing the admin models from the command needs the full `Settings` (a JWT secret) — report it; the command must work with only `DOTRIX_DATABASE_URL`.
- You are asked to run the command against a database that is not a throwaway test database.

## Maintenance notes

- Plan 012 adds roles and a disabled flag; `create_admin` then needs a `role` argument (default owner for the command line, since it is the break-glass path).
- Once invites exist (plan 012), the web sign-up and `DOTRIX_ADMIN_BOOTSTRAP_TOKEN` can be removed; that is a decision for the maintainer.
- A reviewer should check that no password or hash is ever printed or logged.
