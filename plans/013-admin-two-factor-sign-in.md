# Plan 013: Admins sign in with a second factor (TOTP)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/backend/src/dotrix_backend/modules/admin apps/admin/src apps/backend/pyproject.toml`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition. (Earlier plans in this series change
> some of the same files; where "Depends on" names a plan, its changes are
> expected.)

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (sign-in code; a lockout path must exist)
- **Depends on**: plans/011-admin-accounts-from-the-server.md (the command-line reset is the way out of a lost device); plans/012-several-admins-invites-and-roles.md (roles)
- **Category**: security
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

The admin console reads across every workspace of the deployment, and today a password alone opens it. A reused or phished password is enough. After this plan each admin enrols an authenticator app (time-based one-time codes), sign-in needs the code after the password, each admin gets ten single-use recovery codes, and an operator can clear someone's second factor from the server's command line if a device is lost. Enrolment is required: an admin without a second factor can sign in only far enough to set one up.

## Current state

The admin console (`apps/admin`) has its own accounts in `apps/backend/src/dotrix_backend/modules/admin`:

- `models.py` — `AdminUser`, `AdminSession` (and, after plan 012, `AdminInvite`, `AdminUser.role` / `disabled_at`).
- `service.py` — `AdminService` (`signup`, `login`, `refresh`, `logout`, `read`, `_tokens`) and the `get_admin` dependency (`AdminDep`), which decodes the `dtx_admin_access` cookie (a JWT with `sub`, `sid`, `type="admin"`) and checks the `AdminSession` row.
- `router.py` — `/v1/admin/login` and friends; cookies are set by `_set_session(response, access, refresh, settings)` (httpOnly, `SameSite=Strict`). Login is rate-limited with `ThrottleDep` from `modules/auth/limits.py`.
- `apps/admin/src/App.tsx` — the `Login` component and the shell.
- Tests: `apps/backend/tests/integration/test_admin.py` (`_admin(db_client)` creates and signs in the first admin).

`login` today returns the session directly:

```python
    async def login(self, data: AdminLogin) -> tuple[str, str]:
        admin = await self.session.scalar(select(AdminUser).where(AdminUser.email == data.email.lower()))
        if admin is None or not verify_password(admin.password_hash, data.password):
            raise Unauthorized("Wrong email or password")
        pair = await self._tokens(admin)
        await self.session.commit()
        return pair
```

There is no TOTP library in the project (`grep -n pyotp uv.lock` finds nothing). Secrets at rest use `core/crypto.py`:

```python
class Secrets:
    @classmethod
    def from_settings(cls, settings: Settings) -> Secrets: ...
    @property
    def configured(self) -> bool: ...
    def encrypt(self, value: str) -> str: ...
    def decrypt(self, token: str) -> str | None: ...
```

`request.app.state.secrets` holds the app's instance. CI installs with `uv sync --locked`, so a new dependency needs `uv lock` in the same change.

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

- `apps/backend/pyproject.toml`, `uv.lock` (add `pyotp`; run `uv lock`)
- `apps/backend/src/dotrix_backend/modules/admin/models.py`, `schemas.py`, `service.py`, `router.py`, `accounts.py`, and `apps/backend/src/dotrix_backend/admin_cli.py`
- `apps/backend/migrations/versions/<new>.py` (create)
- `apps/backend/tests/integration/test_admin_two_factor.py` (create); `tests/integration/test_admin.py` and `test_admin_accounts.py` helpers only where sign-in now needs a code
- `apps/admin/src/App.tsx`, `api.ts`, `pages.tsx`, `admin.css`
- `deploy/README.md`, `packages/api-client/*` (via `pnpm openapi`), `CHANGELOG.md`

**Out of scope** (do NOT touch):

- Two-factor for app users (`modules/auth`) — a separate feature.
- WebAuthn / passkeys, SMS or email codes.
- Remembering a device to skip the code.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/013-admin-two-factor-sign-in origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Dependency, model, migration

Add `pyotp` to `apps/backend/pyproject.toml` dependencies and run `uv lock`. In `models.py` add to `AdminUser`: `totp_secret_encrypted: Mapped[str | None]` (`String(400)`), `totp_enabled_at: Mapped[datetime | None]`, `totp_last_step: Mapped[int | None]` (`BigInteger`, the last accepted time step, so a code can't be replayed), and a table `admin_recovery_codes` (`admin_user_id` FK cascade, `code_hash` `String(64)`, `used_at` nullable). Write the migration with a working downgrade.

**Verify**: `uv lock --check` → exit 0; the migrations command → no new operations

### Step 2: A two-step sign-in

- `POST /v1/admin/login` keeps its body. When the admin has a second factor enabled it no longer sets the session cookies: it answers `200 {"second_factor": "totp", "challenge": "<token>"}`. The challenge is a JWT signed like the access token but with `type="admin_2fa"`, `sub` = admin id, 5-minute expiry; it must not be accepted by `get_admin` (which already requires `type == "admin"` and a `sid`).
- `POST /v1/admin/login/verify` `{challenge, code}`: verify the challenge, then the code — either a 6-digit TOTP (`pyotp.TOTP(secret).verify(code, valid_window=1)`, refusing a time step `<= totp_last_step`, then storing the step) or a recovery code (hash with `hash_token`, must be unused; mark `used_at`). On success set the session cookies with `_set_session`. Rate-limit by admin email with `ThrottleDep` exactly as login is; a wrong code is `Unauthorized("That code didn't work")`.
- When the admin has **no** second factor yet, `login` issues a normal session but flagged for enrolment only: add a boolean claim `enrol` to the access token (extend `_admin_token`) and make `get_admin` raise `Forbidden("Set up two-factor sign-in first")` when the claim is true, **except** for a new dependency `get_admin_enrolling` used only by `/me`, `/logout`, `/refresh` and the enrolment routes below. `AdminRead` gains `two_factor: bool` and `must_enrol: bool`.
- Enrolment routes (admin session, enrolling allowed): `POST /me/two-factor/start` → generates a secret (`pyotp.random_base32()`), stores it encrypted (not yet enabled) and returns `{secret, otpauth_uri}` (`pyotp.TOTP(secret).provisioning_uri(name=admin.email, issuer_name="dotrix admin")`); `POST /me/two-factor/confirm` `{code}` → verifies, sets `totp_enabled_at`, creates ten recovery codes (random strings from `generate_token`, shown once in the response, stored hashed), and replaces the session with a full one (no `enrol` claim).
- `POST /me/two-factor/recovery-codes` `{code}` (full session + a current code) → replaces the recovery codes.
- If `request.app.state.secrets.configured` is false, enrolment answers the existing `EncryptionNotConfigured` error and `login` behaves as today (no enrolment forced): the server can't store a TOTP secret without `DOTRIX_ENCRYPTION_KEY`. Say so in `deploy/README.md`.

### Step 3: The way out

In `modules/admin/accounts.py` add `reset_admin_two_factor(session, *, email)` (clears the secret, `totp_enabled_at`, `totp_last_step`, deletes recovery codes, revokes the admin's sessions) and a `reset-two-factor --email E` subcommand in `admin_cli.py`. With plan 012 present, also let an owner do it for another admin: `POST /v1/admin/admins/{admin_id}/two-factor/reset` (owner only; never for themselves through this route).

### Step 4: Tests

Create `tests/integration/test_admin_two_factor.py`. Generate codes in tests with `pyotp.TOTP(secret).now()`. Cases: a new admin must enrol (observability routes 403 until confirmed, `/me` works); enrol → confirm → recovery codes returned once; sign-in then needs the code (login alone sets no cookie); a wrong code is refused; the same code can't be used twice; a recovery code works once; the challenge token is refused as a session (`GET /me` with it as the cookie → 401); `reset_admin_two_factor` puts the admin back to "must enrol" and signs them out; with encryption not configured, sign-in works as before. Update the `_admin` helpers in the existing admin test files so their admins are enrolled (one small shared helper that enrols and leaves the client signed in), keeping every existing assertion.

**Verify**: `uv run pytest apps/backend/tests/integration -q -k admin` → all pass

### Step 5: The console

`pnpm openapi`. In `App.tsx`: after the password step, when the API answers with a challenge, show a code field (6 digits, `inputMode="numeric"`, `autoComplete="one-time-code"`) with "Use a recovery code" as an alternative; when `me.must_enrol`, show only the set-up screen: the secret as text and the `otpauth://` link (a QR code needs a library; do not add one), a code field to confirm, then the ten recovery codes once with an "I've saved these" button. Never store the secret, codes or challenge in `localStorage`.

### Step 6: Docs and changelog

`deploy/README.md`: two-factor is required for admins and needs `DOTRIX_ENCRYPTION_KEY`; a lost device is fixed with `python -m dotrix_backend.admin_cli reset-two-factor --email …`. CHANGELOG → Security: `- Admin console sign-in needs a code from an authenticator app, with recovery codes for a lost device.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- New file `tests/integration/test_admin_two_factor.py` (Step 4), modelled on `tests/integration/test_admin.py`.

## Done criteria

- [ ] `uv run pytest apps/backend/tests/integration -q -k admin` exits 0
- [ ] `uv lock --check` exits 0; the migrations command reports no new operations
- [ ] `uv run python apps/backend/scripts/export_openapi.py && git diff --exit-code packages/api-client/openapi.json` exits 0
- [ ] No log or print statement in `modules/admin` mentions the TOTP secret, a code or a recovery code (`grep -rnE "logger|print\(" apps/backend/src/dotrix_backend/modules/admin` and read each hit)
- [ ] `uv run ruff check apps packages` exits 0, and the TS checks exit 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- Plans 011 or 012 have not landed on your base branch.
- `pyotp` cannot be added (no network, or a lock conflict) — do not hand-roll TOTP.
- Making existing admin tests pass seems to require weakening the enrolment rule.

## Maintenance notes

- A reviewer should check: the challenge token can never act as a session; codes can't be replayed; nothing secret is logged or stored in the browser; the lockout path (command line) works.
- Deferred: passkeys; remembering a trusted device; a QR code (needs a client library).
- Existing deployments: every admin is asked to enrol at their next sign-in.
