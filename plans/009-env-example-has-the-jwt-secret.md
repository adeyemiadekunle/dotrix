# Plan 009: Following the README's setup gives a backend that starts (`DOTRIX_JWT_SECRET` is documented)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat f477722..HEAD -- .env.example README.md apps/backend/src/dotrix_backend/core/settings.py`
> If any of these changed since this plan was written, compare the "Current
> state" excerpts against the live files before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `f477722`, 2026-11-11

## Why this matters

The backend refuses to start without `DOTRIX_JWT_SECRET` (a required setting
with no default, at least 32 characters). The README's getting-started steps
say `cp .env.example .env`, "then replace every change-me", and its
**Required** list names only the encryption key and the passwords. But
`.env.example` has no `DOTRIX_JWT_SECRET` line at all. Someone following the
README exactly gets a pydantic "Field required" error the first time they run
`pnpm dev:backend` or `pnpm docker:up`, with nothing pointing at the fix. It
is the first thing a new contributor (or a coding agent setting up the repo)
hits. After this plan the variable is in `.env.example` with how to generate
it, the README lists it as required, and a test stops required settings from
going undocumented again.

## Current state

- `apps/backend/src/dotrix_backend/core/settings.py:58-60`:

```python
    # Auth. The secret is required and never has a default.
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_issuer: str = "dotrix"
```

- `.env.example` — `grep -c JWT .env.example` prints `0`. Its backend section starts at line 20:

```
# Backend (apps/backend), read with the DOTRIX_ prefix
DOTRIX_ENV=development
# Organisation workspaces (teams: invites, roles, members). Unset: on in development and tests,
# off on staging and production, where personal workspaces launch first.
# DOTRIX_ORGANISATIONS=false
DOTRIX_DATABASE_URL=""
DOTRIX_REDIS_URL=redis://127.0.0.1:6379/0
```

  and the encryption key appears later, commented out (line 117):

```
# Personal keys are stored encrypted with this Fernet key
# (python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())").
# Comma-separated to rotate: the first encrypts, every one decrypts.
# DOTRIX_ENCRYPTION_KEY=change-me
```

- `README.md:157-164` (Getting started):

```bash
uv sync                  # Python: engine, CLI, backend + dev tools
pnpm install             # TypeScript apps and packages
cp .env.example .env     # then replace every change-me
```

- `README.md:184-188` (Configuration):

```markdown
**Configuration** (all in `.env`, explained in [.env.example](.env.example)):
- **Required:**
  - `DOTRIX_ENCRYPTION_KEY`: a Fernet key that encrypts people's model keys and saved coding
    sessions.
  - The Postgres and storage passwords.
```

- Already documented for production only: `deploy/dokploy.env.example:2,14` ("Passwords and DOTRIX_JWT_SECRET: `openssl rand -hex 32`") and `deploy/docker-compose.dokploy.yml:25`.
- `infra/docker-compose.app.yml:27` passes `.env` to the Docker services (`env_file: .env`), so `pnpm docker:up` has the same requirement.
- Settings unit tests live in `apps/backend/tests/unit/test_settings.py` and build settings with a local `settings(...)` helper.

Required settings = fields of `DatabaseSettings`/`Settings` with no default.
At planning time those are `database_url` and `jwt_secret` only.

Convention: `.env.example` never contains a real secret; placeholders are the
literal text `change-me…`. Never put a generated secret into a committed file.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync` | exit 0 |
| Settings tests | `uv run pytest apps/backend/tests/unit/test_settings.py -q` | all pass |
| Lint | `uv run ruff check apps packages` | exit 0 |
| Format check | `pnpm format:check` | exit 0 |

## Scope

**In scope**:

- `.env.example`
- `README.md` (the Getting started and Configuration parts only)
- `apps/backend/tests/unit/test_settings.py` (add one test)

**Out of scope** (do NOT touch):

- `core/settings.py` — do not give `jwt_secret` a default; "required and never has a default" is deliberate.
- Your own `.env` — never commit it, never print its contents.
- Documenting the ~50 optional settings missing from `.env.example` — a separate docs task.
- `deploy/` — already documents the variable.
- `CHANGELOG.md` — this changes no behaviour for people using dotrix; if the repo's PR checks insist on a changelog line, add under `### Changed`: `- Setup: .env.example now includes the required DOTRIX_JWT_SECRET.`

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/009-env-example-jwt origin/stage`. PRs go into `stage`, never `main`.
- Commit message: one short sentence-case line (e.g. `.env.example: the required DOTRIX_JWT_SECRET, and how to make one`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the variable to `.env.example`

Directly after the `DOTRIX_ENV=development` line, add:

```
# Signs sign-in tokens. Required, at least 32 characters, never the same in two deployments:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
DOTRIX_JWT_SECRET=change-me-to-a-long-random-string-of-32-or-more-characters
```

The placeholder is intentionally longer than 32 characters so that a developer
who forgets to replace it gets a running local server rather than a confusing
validation error — and it contains `change-me`, which the README tells them to
replace.

**Verify**: `grep -c "^DOTRIX_JWT_SECRET=change-me" .env.example` → `1`

### Step 2: List it in the README

In `README.md`, in the **Required** list, add a first bullet:

```markdown
  - `DOTRIX_JWT_SECRET`: signs sign-in tokens; at least 32 random characters
    (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
```

Keep the two existing bullets after it.

**Verify**: `grep -n "DOTRIX_JWT_SECRET" README.md` → at least one line inside the Configuration section

### Step 3: A test that keeps required settings documented

In `apps/backend/tests/unit/test_settings.py` add a test that reads the
repo-root `.env.example` and checks every required setting has an active
(uncommented) line:

```python
def test_every_required_setting_is_in_env_example() -> None:
    """Whatever the server can't start without is in .env.example, uncommented, so the README's
    `cp .env.example .env` gives a server that starts."""
    from pathlib import Path

    from dotrix_backend.core.settings import Settings

    example = (Path(__file__).resolve().parents[4] / ".env.example").read_text(encoding="utf-8")
    names = {line.split("=", 1)[0].strip() for line in example.splitlines() if "=" in line and not line.lstrip().startswith("#")}
    required = {f"DOTRIX_{name.upper()}" for name, field in Settings.model_fields.items() if field.is_required()}
    assert required <= names, f"missing from .env.example: {sorted(required - names)}"
```

`parents[4]` is the repository root from `apps/backend/tests/unit/` (unit →
tests → backend → apps → root). Check with
`python -c "from pathlib import Path; print(Path('apps/backend/tests/unit/test_settings.py').resolve().parents[4])"`
and adjust the index if the printed path is not the repository root. Keep line
length within the file's existing style (wrap the long comprehension if Ruff
complains).

**Verify**:
- `uv run pytest apps/backend/tests/unit/test_settings.py -q` → all pass, including the new test
- Temporarily prove the test bites: comment out the new `DOTRIX_JWT_SECRET` line in `.env.example`, run the test (it must FAIL naming `DOTRIX_JWT_SECRET`), then restore the line and run it again (it must pass).

### Step 4: Lint and format

**Verify**: `uv run ruff check apps packages` → exit 0, and `pnpm format:check` → exit 0

## Test plan

- One new unit test (Step 3) in the existing settings test file.
- No integration tests needed.

## Done criteria

- [ ] `grep -c "^DOTRIX_JWT_SECRET=" .env.example` → 1, and the value contains `change-me`
- [ ] `uv run pytest apps/backend/tests/unit/test_settings.py -q` exits 0 with the new test
- [ ] `uv run ruff check apps packages` exits 0
- [ ] `git diff` contains no real secret (the only value added is the `change-me…` placeholder)
- [ ] `git status --short` lists only in-scope files (and not `.env`)
- [ ] `plans/README.md` status row updated

## STOP conditions

- The excerpts in "Current state" do not match the live files.
- The new test reports required settings other than `DOTRIX_DATABASE_URL` and `DOTRIX_JWT_SECRET` as missing — report the names; do not invent placeholder values for settings you do not understand.
- `.env.example` already has an uncommented `DOTRIX_DATABASE_URL=""` (it does at planning time). If the test fails on it because of the empty quoted value, the parsing in the test is wrong — fix the test, not the file.

## Maintenance notes

- When a new setting without a default is added to `Settings`, the new test fails until `.env.example` gets a line for it — that is the point.
- Related docs drift, not fixed here: about half of the optional settings have no entry in `.env.example`, and the storage variables are still named `MINIO_ROOT_*` although the local store is RustFS.
