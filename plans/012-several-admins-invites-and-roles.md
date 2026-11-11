# Plan 012: Several people can be admins: invites, two roles, and a way to remove someone

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/backend/src/dotrix_backend/modules/admin apps/admin/src apps/backend/src/dotrix_backend/core/settings.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED (authentication code and a migration)
- **Depends on**: plans/011-admin-accounts-from-the-server.md (reuses `modules/admin/accounts.py`)
- **Category**: security
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

Today exactly one admin account can exist: sign-up closes after the first. A team operating dotrix has to share one password, cannot tell who did what, and cannot remove one person's access without locking everyone out. After this plan an admin with the owner role invites others by email; each invitee sets their own password from a single-use link; there are two roles (owner manages admins, viewer only reads); an owner can disable or remove an admin, which signs them out everywhere; and each admin can change their own password.

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

Patterns to copy from the app's own accounts and invites:

- Single-use emailed tokens: `modules/auth/models.py` `ActionToken` and `modules/auth/service.py` `_new_action_token` / `_consume` (the raw token goes only in the email; the row stores `hash_token(raw)`, `expires_at`, `used_at`; lookups use `get_by_hash_for_update`).
- Sending email: enqueue the `send_email` job (`dotrix_backend/jobs.py`: `send_email(ctx, *, to, subject, body, html=None)`) through `request.app.state.jobs.enqueue("send_email", ...)`; see how `modules/auth` sends its verification email and copy that call shape. In tests the `outbox` fixture (`OutboxEmailSender`) collects messages and `email_token("/path")` extracts a token from the last link (see `tests/integration/test_magic_link.py`).
- Links in emails are built from `settings.app_url` for the app. The admin console has its own origin, so this plan adds a setting for it.
- Rate limits: `modules/auth/limits.py` (`LOGIN`, `ThrottleDep`), already used by admin login.

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

- `apps/backend/src/dotrix_backend/core/settings.py` (one setting)
- `apps/backend/src/dotrix_backend/modules/admin/models.py`, `schemas.py`, `service.py`, `router.py`, `accounts.py`
- `apps/backend/migrations/versions/<new>.py` (create)
- `apps/backend/tests/integration/test_admin_accounts.py` (create), `tests/integration/test_admin.py` (only if an existing assertion must change; say why)
- `apps/admin/src/App.tsx`, `apps/admin/src/api.ts`, `apps/admin/src/pages.tsx`, `apps/admin/src/admin.css` (an Admins page and the accept-invite screen)
- `.env.example`, `deploy/docker-compose.dokploy.yml`, `deploy/dokploy.env.example`, `deploy/README.md`
- `packages/api-client/openapi.json`, `packages/api-client/src/schema.ts` (via `pnpm openapi` only), `CHANGELOG.md`

**Out of scope** (do NOT touch):

- Two-factor sign-in (plan 013) and the trail of admin actions (plan 014).
- Single sign-on. Not in scope; the maintainer deferred it.
- The observability routes' behaviour: every existing `/v1/admin/observe/*` and `/v1/admin/audit` route stays readable by both roles.
- Removing the web sign-up or `DOTRIX_ADMIN_BOOTSTRAP_TOKEN`.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/012-several-admins-invites-and-roles origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change (e.g. `Admin console's first sign-up needs a deployment setup token`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Model and migration

In `modules/admin/models.py`:

- `AdminUser`: add `role: Mapped[str]` (`String(16)`, values `"owner"` / `"viewer"`, server default `"owner"` so existing accounts become owners), `disabled_at: Mapped[datetime | None]`, `password_changed_at: Mapped[datetime | None]`. Drop the unused `workspace_id` and `user_id` columns (grep the repo first: `grep -rn "admin.workspace_id\|admin.user_id\|AdminUser(.*workspace_id" apps/backend/src`; `AdminService.read` builds `AdminRead.workspace` from `workspace_id` — remove that field from `AdminRead` and from `read()` too, and from `apps/admin/src/api.ts` if referenced).
- New `AdminInvite(UUIDPrimaryKeyMixin, Base)`, table `admin_invites`: `email` (`String(320)`), `role` (`String(16)`), `token_hash` (`String(64)`, unique), `invited_by_id` (FK `admin_users.id`, `ondelete="SET NULL"`, nullable), `created_at`, `expires_at`, `accepted_at` (nullable), `revoked_at` (nullable).

Register nothing new in `db/models.py` unless `admin.models` is not already imported there (check). Write the migration by hand in the repo's style (see `20261103_1500_f94a6db03217_first_onboarding_workspace.py`), with a working `downgrade()`.

**Verify**: the "Migrations match models" command from the table → no new operations detected

### Step 2: Sign-in respects disabled accounts and roles

- `login`: a disabled admin gets the same `Unauthorized("Wrong email or password")` as a wrong password.
- `get_admin`: after loading the admin, `if admin.disabled_at is not None: raise Unauthorized("Sign in to the Admin app again")`.
- Add a dependency `require_owner(admin: AdminDep) -> AdminUser` that raises `Forbidden("Only an owner can manage admins")` for viewers, and `OwnerDep = Annotated[AdminUser, Depends(require_owner)]`.
- `AdminRead` gains `role`.

### Step 3: The setting for links

`core/settings.py`: `admin_url: str | None = None` with a comment (the admin console's own address, used for links in admin emails; unset: invites can't be emailed and the API returns the link's path for the owner to pass on). Document it in `.env.example`, `deploy/dokploy.env.example`, `deploy/docker-compose.dokploy.yml` (same style as `DOTRIX_APP_URL`) and `deploy/README.md`.

### Step 4: Service and routes

Add to `AdminService` (or a new `AdminAccounts` service in `accounts.py`; keep routers free of queries) and expose under `/v1/admin`:

| Route | Who | Behaviour |
|---|---|---|
| `GET /admins` | owner | Every admin: id, email, name, role, created_at, disabled_at, last sign-in (max `AdminSession.created_at`). |
| `POST /admins/invites` `{email, role}` | owner | Refuse if an active admin has that email (`Conflict`). Revoke any earlier pending invite for that email, create one valid 72 hours, email the link `{admin_url}/#/accept?token=…`. Rate-limited with the existing `ThrottleDep`. Returns the invite (never the token). |
| `GET /admins/invites` | owner | Pending invites (not accepted, not revoked, not expired). |
| `DELETE /admins/invites/{invite_id}` | owner | Sets `revoked_at`. |
| `POST /invites/preview` `{token}` | no sign-in | The invite's email and role if the token is usable, else `InvalidLink` (see `core/errors.py`). Token in the body, never the URL path. |
| `POST /invites/accept` `{token, name, password}` | no sign-in | Lock the invite row (`with_for_update`), check it is usable, create the admin with the invite's email and role via `create_admin`, mark `accepted_at`, sign the new admin in (`_set_session`). Rate-limited. |
| `PATCH /admins/{admin_id}` `{role?, disabled?}` | owner | Change role, disable or re-enable. Disabling revokes all that admin's sessions. |
| `DELETE /admins/{admin_id}` | owner | Deletes the admin (sessions cascade). |
| `POST /me/password` `{current_password, new_password}` | any admin | Verify the current password, set the new one, set `password_changed_at`, revoke the admin's **other** sessions (keep the one making the call). |
| `POST /me/sessions/revoke-others` | any admin | Sign out everywhere else. |

Rules that must hold, each with a test: the last active owner cannot be demoted, disabled or deleted (`Conflict("There must be at least one owner")`); an owner cannot disable or delete themselves through `PATCH`/`DELETE` if that would leave no other owner; a viewer gets 403 on every owner route; an invite token works once; an expired or revoked invite is refused; passwords need at least 12 characters. Serialise the "last owner" check and the write with the advisory lock already used by `signup` (`pg_advisory_xact_lock(hashtextextended("admin:bootstrap", 0))`).

**Verify**: `uv run ruff check apps/backend` → exit 0; `uv run pytest apps/backend/tests/unit/test_openapi.py -q` → all pass

### Step 5: Tests

Create `tests/integration/test_admin_accounts.py`, modelled on `test_admin.py` (reuse its `ADMIN` dict and `_admin` helper by import). Cover every row of the table and every rule in Step 4, plus: after an owner disables a viewer, the viewer's existing cookie is rejected on `GET /v1/admin/observe/health` (401); a viewer can still read `GET /v1/admin/observe/health` (200) before that; the invite email goes to the invited address and its body contains the link but the API response does not contain the token.

**Verify**: `uv run pytest apps/backend/tests/integration/test_admin_accounts.py apps/backend/tests/integration/test_admin.py -q` → all pass

### Step 6: The console

Run `pnpm openapi`. In `apps/admin`:

- `api.ts`: `Me` gains `role`; add the calls above. Non-GET calls go through a new `send(path, method, body)` helper that retries once after a 401 like `call` does.
- `App.tsx`: when the URL hash is `#/accept?token=…` and nobody is signed in, show an "Accept your invite" card (calls preview, then name + password + confirm, then accept). Keep the token out of `localStorage` and logs.
- A new page `Admins` in `PAGES` (owners only; hide it from viewers): a table of admins (role, last sign-in, state) with Change role / Disable / Remove behind a confirm, a pending-invites list with Revoke, and an "Invite an admin" form (email, role). When `admin_url` is unset the API returns a note; show it.
- An account menu entry "Change password" (current, new, confirm) for everyone.
- Follow the existing markup and classes in `pages.tsx` / `admin.css`; sentence case.

**Verify**: the "TS checks" command → exit 0; `pnpm --filter @dotrix/admin build` → exit 0

### Step 7: Changelog

Unreleased → Added: `- The admin console supports several admins: an owner invites others by email, each sets their own password, owners and viewers have different rights, and an owner can disable or remove an admin.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- New file `tests/integration/test_admin_accounts.py` (Step 5). Pattern: `tests/integration/test_admin.py` and, for emailed tokens, `tests/integration/test_magic_link.py`.
- The console has no unit tests; its checks are typecheck, lint and build.

## Done criteria

- [ ] `uv run pytest apps/backend/tests/integration/test_admin_accounts.py apps/backend/tests/integration/test_admin.py apps/backend/tests/unit/test_openapi.py -q` exits 0
- [ ] The migrations command reports no new operations; `alembic downgrade -1 && alembic upgrade head` both succeed
- [ ] `uv run ruff check apps packages` and the TS checks exit 0
- [ ] `uv run python apps/backend/scripts/export_openapi.py && git diff --exit-code packages/api-client/openapi.json` exits 0
- [ ] `grep -rn "token" apps/admin/src | grep -i "localStorage\|console.log"` returns nothing
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- Plan 011's `modules/admin/accounts.py` does not exist on your base branch (the dependency has not landed).
- Dropping `workspace_id` / `user_id` breaks something outside `modules/admin` and `apps/admin`.
- An existing test in `test_admin.py` fails for a reason other than the removed `workspace` field of `AdminRead`.
- You cannot find how the app enqueues an email from a request; do not send email inline from the route.

## Maintenance notes

- Plan 013 (two-factor) changes `login`; plan 014 (trail) records the actions added here. Land them after this.
- A reviewer should check every owner route has `OwnerDep`, the last-owner rule, and that no response or log carries an invite token.
- Deferred: removing the web sign-up and its setup token now that invites exist; single sign-on.
