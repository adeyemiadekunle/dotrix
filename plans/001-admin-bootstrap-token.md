# Plan 001: The first admin account can only be created with a deployment secret

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat f477722..HEAD -- apps/backend/src/dotrix_backend/modules/admin apps/backend/src/dotrix_backend/core/settings.py apps/admin/src/App.tsx deploy`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `f477722`, 2026-11-11

## Why this matters

The admin console shows data across every workspace (names, usage, run history,
failure text, the audit log). Its first account is created by
`POST /v1/admin/signup`, which needs no authentication and no proof of anything:
it is open to whoever reaches it first while no admin exists. On a fresh
deployment, or one where the operator has not yet claimed the console, a stranger
becomes the platform admin and sign-up then closes to the real operator. The docs
say sign-up requires "proving you own the workspace", but no such check exists in
the code. After this plan, sign-up on a deployed server requires a secret that only
the operator has, the check-and-insert can no longer race, and the docs match.

## Current state

Files and roles:

- `apps/backend/src/dotrix_backend/modules/admin/service.py` — `AdminService`; `bootstrap_available()` and `signup()` (lines 68-86).
- `apps/backend/src/dotrix_backend/modules/admin/router.py` — routes under `/v1/admin`; `admin_bootstrap` (line 72) and `admin_signup` (lines 79-85).
- `apps/backend/src/dotrix_backend/modules/admin/schemas.py` — `AdminSignup` (lines 13-19), `AdminBootstrap` (lines 42-45).
- `apps/backend/src/dotrix_backend/core/settings.py` — `Settings` (pydantic-settings, `DOTRIX_` prefix), `is_deployed` property, `_safe_for_production` validator.
- `apps/admin/src/App.tsx` — the console's `Login` component (lines 70-130) shows the sign-up form while `/admin/bootstrap` says `enabled: true`.
- `apps/backend/tests/integration/test_admin.py` — existing tests; `_admin()` helper posts `ADMIN` to `/v1/admin/signup`.
- `deploy/nginx.conf` — the web app's nginx; line 13 forwards all of `/v1` (including `/v1/admin`) to the API on the app's own origin.
- `deploy/docker-compose.dokploy.yml`, `deploy/dokploy.env.example`, `deploy/README.md`, `.env.example` — deployment configuration and docs.

`service.py:68-86` today:

```python
    async def bootstrap_available(self) -> bool:
        """Sign-up is open only while no admin account exists — the console is for the person
        operating the deployment, never for app users."""
        return not await self.session.scalar(select(func.count(AdminUser.id)))

    async def signup(self, data: AdminSignup) -> tuple[str, str]:
        if not await self.bootstrap_available():
            raise Forbidden("Admin sign-up is closed")
        admin = AdminUser(
            email=data.email.lower(),
            name=data.name,
            password_hash=hash_password(data.password),
            created_at=datetime.now(UTC),
        )
        self.session.add(admin)
        await self.session.flush()
        pair = await self._tokens(admin)
        await self.session.commit()
        return pair
```

`schemas.py:13-19` today:

```python
class AdminSignup(BaseModel):
    """Create an admin account by proving you own the workspace: your app account's email and
    password. The admin gets its own credentials from then on — separate from your sign-in."""

    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)
```

`deploy/README.md:48-49` says: "whoever operates dotrix creates their console
account there by proving they own a workspace." That is not implemented.

Conventions to match:

- Settings: secrets are `SecretStr | None` fields with a comment above them; deployment-only rules go in `_safe_for_production` (see `core/settings.py`, e.g. the `email_backend == "console"` check).
- Errors: raise domain exceptions from `dotrix_backend.core.errors` (`Forbidden`, `Unauthorized`), never `HTTPException`.
- Constant-time comparison: `hmac.compare_digest` (exemplar: `modules/connectors/webhook.py:31-34`).
- Advisory lock exemplar (`modules/graph/service.py:85`):
  `select(func.pg_advisory_xact_lock(func.hashtextextended(f"graph:{project.id}", 0)))`
- Every route has a docstring and `responses=errors(...)`; `tests/unit/test_openapi.py` enforces it.
- Copy in the UI is sentence case.
- Secrets never go in code, logs, tests' real values, or this plan. Use obvious fakes in tests (e.g. `"test-bootstrap-token-0123456789"`).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync && pnpm install` | exit 0 |
| Local services (tests need Postgres) | `pnpm db:up` | containers running |
| Admin tests | `uv run pytest apps/backend/tests/integration/test_admin.py apps/backend/tests/unit/test_settings.py -q` | all pass |
| OpenAPI docs rules | `uv run pytest apps/backend/tests/unit/test_openapi.py -q` | all pass |
| Python lint | `uv run ruff check apps packages` | exit 0 |
| Regenerate API schema + TS client | `pnpm openapi` | exit 0; `packages/api-client/openapi.json` and `src/schema.ts` updated |
| TS checks | `pnpm typecheck && pnpm exec eslint . && pnpm format:check` | exit 0 |

Tests read the database URL from `.env` (`DOTRIX_DATABASE_URL`) or
`DOTRIX_TEST_DATABASE_URL`; if `uv run pytest` cannot connect, that is an
environment problem, not a plan failure — report it.

## Scope

**In scope** (the only files you should modify):

- `apps/backend/src/dotrix_backend/core/settings.py`
- `apps/backend/src/dotrix_backend/modules/admin/service.py`
- `apps/backend/src/dotrix_backend/modules/admin/schemas.py`
- `apps/backend/src/dotrix_backend/modules/admin/router.py` (docstrings only)
- `apps/backend/tests/integration/test_admin.py`
- `apps/backend/tests/unit/test_settings.py`
- `apps/admin/src/App.tsx`
- `packages/api-client/openapi.json`, `packages/api-client/src/schema.ts` (generated by `pnpm openapi` only — never hand-edit)
- `deploy/nginx.conf`, `deploy/docker-compose.dokploy.yml`, `deploy/dokploy.env.example`, `deploy/README.md`, `.env.example`
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- `modules/admin/platform.py` and every other admin route — only sign-up changes.
- The `AdminUser` model and migrations — no schema change is needed.
- `deploy/admin.nginx.conf` — the admin origin must keep forwarding `/v1/admin`.
- Implementing "prove you own a workspace" — the decision here is a deployment secret instead; the docs are corrected to say so.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/001-admin-bootstrap-token origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change, as in `git log` (e.g. `NVIDIA as a model provider (build.nvidia.com's hosted models)`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the setting

In `core/settings.py`, in `Settings`, after the `jwt_issuer` line, add:

```python
    # The secret that opens the admin console's first sign-up (apps/admin). Required to create
    # that account on staging and production; unset there, admin sign-up stays closed.
    admin_bootstrap_token: SecretStr | None = Field(default=None, min_length=24)
```

Do not add a `_safe_for_production` error for it being unset: an operator who
never uses the console must still be able to start the server.

**Verify**: `uv run python -c "from dotrix_backend.core.settings import Settings; print('admin_bootstrap_token' in Settings.model_fields)"` → `True`

### Step 2: Require the token in the service, and serialise sign-up

In `modules/admin/schemas.py`, replace `AdminSignup`'s docstring and add a field:

```python
class AdminSignup(BaseModel):
    """Create the first admin account. On a deployed server this needs the deployment's
    bootstrap token (DOTRIX_ADMIN_BOOTSTRAP_TOKEN). The admin has its own credentials,
    separate from any app account."""

    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    bootstrap_token: str | None = Field(default=None, max_length=200)
```

Update `AdminBootstrap` to tell the form whether to ask for the token:

```python
class AdminBootstrap(BaseModel):
    """Whether the sign-up form is open (no admin account exists, and on a deployed server the
    bootstrap token is configured), and whether it asks for that token."""

    enabled: bool
    token_required: bool = False
```

In `modules/admin/service.py` add `import hmac` at the top, and replace
`bootstrap_available` and `signup` with:

```python
    def _token_required(self) -> bool:
        return self.settings.admin_bootstrap_token is not None or self.settings.is_deployed

    async def bootstrap_available(self) -> bool:
        """Sign-up is open only while no admin account exists, and on a deployed server only
        when its bootstrap token is configured: the console is for whoever operates the
        deployment, never for app users."""
        if self.settings.is_deployed and self.settings.admin_bootstrap_token is None:
            return False
        return not await self.session.scalar(select(func.count(AdminUser.id)))

    async def signup(self, data: AdminSignup) -> tuple[str, str]:
        # One sign-up at a time, so two requests can't both find "no admin yet".
        await self.session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended("admin:bootstrap", 0)))
        )
        if not await self.bootstrap_available():
            raise Forbidden("Admin sign-up is closed")
        expected = self.settings.admin_bootstrap_token
        if expected is not None and not hmac.compare_digest(
            expected.get_secret_value().encode(), (data.bootstrap_token or "").encode()
        ):
            raise Forbidden("Admin sign-up is closed")
        admin = AdminUser(
            email=data.email.lower(),
            name=data.name,
            password_hash=hash_password(data.password),
            created_at=datetime.now(UTC),
        )
        self.session.add(admin)
        await self.session.flush()
        pair = await self._tokens(admin)
        await self.session.commit()
        return pair
```

The same error text for "closed" and "wrong token" is deliberate: it does not
reveal which one failed. Also fix the module docstring at the top of
`service.py` (lines 1-6): it describes a workspace pseudo-membership that does
not exist. Replace it with a truthful two-sentence description: admin accounts
are created once with the deployment's bootstrap token, then sign in
separately; refresh tokens live in `admin_sessions`, rotated on every use.

In `modules/admin/router.py`, update `admin_bootstrap` to return both fields
(`AdminBootstrap(enabled=await svc.bootstrap_available(), token_required=svc._token_required())`
— rename `_token_required` to a public `token_required` method if you prefer;
keep the name consistent) and update the two docstrings to mention the token.
Do not rename the route functions (`admin_bootstrap`, `admin_signup`): their
names are the OpenAPI operation IDs.

**Verify**: `uv run ruff check apps/backend` → exit 0

### Step 3: Tests

In `apps/backend/tests/integration/test_admin.py` keep `_admin()` unchanged
(tests run with `env=test`, token unset, so sign-up stays open as today) and add
these tests. To set the token for one test, mutate the app's settings object and
restore it: `settings = db_client._transport.app.state.settings` then use
`monkeypatch.setattr(settings, "admin_bootstrap_token", SecretStr("test-bootstrap-token-0123456789"))`
(import `SecretStr` from `pydantic`). `AdminService` is built per request from
`SettingsDep`; if `monkeypatch.setattr` on the settings instance does not take
effect, read `apps/backend/src/dotrix_backend/api/deps.py` to see where
`SettingsDep` comes from and patch that same object.

1. `test_signup_needs_the_bootstrap_token_when_one_is_set`: with the token set,
   `GET /v1/admin/bootstrap` → `{"enabled": true, "token_required": true}`;
   `POST /v1/admin/signup` with no token → 403; with a wrong token → 403; with
   the right token in `bootstrap_token` → 201; bootstrap is then `enabled: false`.
2. `test_a_deployed_server_without_a_token_keeps_signup_closed`: patch
   `settings.env` to `"production"` (monkeypatch, token unset) →
   `GET /v1/admin/bootstrap` returns `enabled: false` and signup → 403.
3. Keep `test_bootstrap_only_while_no_account_exists` passing unchanged.

In `apps/backend/tests/unit/test_settings.py` add one test using the file's
existing `settings(...)` helper: a token shorter than 24 characters is refused
(`pytest.raises(ValidationError)`), and a 24+ character one is accepted.

**Verify**: `uv run pytest apps/backend/tests/integration/test_admin.py apps/backend/tests/unit/test_settings.py apps/backend/tests/unit/test_openapi.py -q` → all pass, including 3 new tests

### Step 4: Regenerate the API schema

Run `pnpm openapi`.

**Verify**: `git diff --stat packages/api-client` shows `openapi.json` and `src/schema.ts` changed, and `grep -c bootstrap_token packages/api-client/openapi.json` → at least 1

### Step 5: Ask for the token in the admin console

In `apps/admin/src/App.tsx`, `Login` component:

- Change the bootstrap query's type to `{ enabled: boolean; token_required?: boolean }`.
- Add `token: ""` to the `f` state.
- When `first` is true, send `{ email, name, password, bootstrap_token: f.token || undefined }`
  as the body (do not send `token` under any other key, and never to `/admin/login`).
- When `first && boot.data?.token_required`, render one more labelled input
  after Name, in the same markup style as the existing fields:
  label text `Setup token`, `className="input"`, `type="password"`,
  `autoComplete="off"`, `required`, bound to `f.token`. Add a short hint under
  the heading paragraph: `Ask whoever deployed dotrix for the setup token (DOTRIX_ADMIN_BOOTSTRAP_TOKEN).`
- Never write the token to `localStorage`, the URL, or a log.

**Verify**: `pnpm typecheck && pnpm exec eslint . && pnpm format:check` → exit 0

### Step 6: Close the route on the app's origin, and document the setting

In `deploy/nginx.conf`, add this block immediately **before** the existing
`location ~ ^/(v1|api|health)(/|$) {` block (nginx uses the first matching
regex location, so order matters):

```nginx
    # The admin console's API is served only on the admin origin (deploy/admin.nginx.conf).
    location ~ ^/v1/admin(/|$) {
        return 404;
    }
```

In `deploy/docker-compose.dokploy.yml`, next to the `DOTRIX_JWT_SECRET` line
(line 25), add `DOTRIX_ADMIN_BOOTSTRAP_TOKEN: ${DOTRIX_ADMIN_BOOTSTRAP_TOKEN:-}`
using the same indentation and quoting style as its neighbours.

In `deploy/dokploy.env.example`, add an empty `DOTRIX_ADMIN_BOOTSTRAP_TOKEN=`
with a one-line comment: needed once, to create the admin console's first
account; generate with `openssl rand -hex 32`; can be removed afterwards.

In `.env.example`, add a commented `# DOTRIX_ADMIN_BOOTSTRAP_TOKEN=` with the
same explanation plus "unset in development: admin sign-up is open until the
first account exists".

In `deploy/README.md` lines 48-49, replace "creates their console account there
by proving they own a workspace" with "creates their console account there with
`DOTRIX_ADMIN_BOOTSTRAP_TOKEN` (the sign-up form asks for it; without the
variable, admin sign-up stays closed)".

**Verify**:
- `grep -n "v1/admin" deploy/nginx.conf` → one match, on a line number lower than the `(v1|api|health)` location's line.
- If Docker is available: `docker run --rm -v "$PWD/deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine nginx -t` → `syntax is ok`. If Docker is not available, skip this check and say so in your report.

### Step 7: Changelog

In `CHANGELOG.md` under `## [Unreleased]`, add a `### Security` section (or
append to it if present) with one line written for people who use dotrix:
`- Creating the admin console's first account now needs the deployment's setup token (DOTRIX_ADMIN_BOOTSTRAP_TOKEN); without it, admin sign-up stays closed on a deployed server.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- New tests in `apps/backend/tests/integration/test_admin.py` (3 cases listed in Step 3) and one in `tests/unit/test_settings.py`.
- Structural pattern: the existing `test_bootstrap_only_while_no_account_exists` in the same file.
- Verification: `uv run pytest apps/backend/tests/integration/test_admin.py apps/backend/tests/unit/test_settings.py -q` → all pass.

## Done criteria

- [ ] `uv run pytest apps/backend/tests/integration/test_admin.py apps/backend/tests/unit/test_settings.py apps/backend/tests/unit/test_openapi.py -q` exits 0 with the new tests present
- [ ] `uv run ruff check apps packages` exits 0
- [ ] `pnpm typecheck && pnpm exec eslint . && pnpm format:check` exit 0
- [ ] `uv run python apps/backend/scripts/export_openapi.py && git diff --exit-code packages/api-client/openapi.json` exits 0 (schema committed and current)
- [ ] `grep -rn "proving you own\|proving they own" apps/backend/src deploy` returns no matches
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- An admin account already exists in a database you are asked to test against and a step seems to require deleting it — never delete admin rows.
- `monkeypatch`-ing the settings object does not change the behaviour of `AdminService` after you have read `api/deps.py` once.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.

## Maintenance notes

- Operators of an existing deployment that already has its admin account are unaffected: sign-up is already closed for them.
- A reviewer should check that the token is compared in constant time, never logged, and never sent to `/admin/login`.
- Deferred: rate limits already apply to sign-up (`throttle(LOGIN, …)`); a separate lockout for repeated wrong tokens was not added.
- Deferred: "prove workspace ownership" as an alternative to the token. If it is ever built, the docstrings changed here must change with it.
