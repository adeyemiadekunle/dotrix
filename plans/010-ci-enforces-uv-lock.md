# Plan 010: CI fails when `uv.lock` is out of date with the Python manifests

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat f477722..HEAD -- .github/workflows/ci.yml deploy/backend.Dockerfile scripts/release.py`
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

Python dependencies are pinned in `uv.lock`. Two places install them, and
neither checks that the lock matches the `pyproject.toml` files:

- CI runs a bare `uv sync`, which **re-resolves and silently rewrites** the lock in the runner when a manifest changed. Tests then run against freshly resolved packages.
- The production image runs `uv sync --frozen`, which installs **exactly the committed lock without checking it**.

So a pull request that adds or bumps a Python dependency but forgets `uv lock`
passes CI, and the production image is then built from the stale lock: the new
import fails at runtime in production (or an old, unpatched version ships).
The TypeScript side already guards against this (`pnpm install --frozen-lockfile`).
A comment in `scripts/release.py` even claims "CI installs with --locked",
which is not true today. After this plan CI installs with `--locked`, which
fails if the lock is out of date.

## Current state

- `.github/workflows/ci.yml:42` (job `python`) and `:133` (job `e2e`):

```yaml
      - run: uv sync
```

- `deploy/backend.Dockerfile:28,34`:

```dockerfile
RUN uv sync --frozen --no-dev --no-install-workspace --package dotrix-backend
...
RUN uv sync --frozen --no-dev --package dotrix-backend
```

- `scripts/release.py:96`:

```python
    # uv.lock records the workspace packages' versions; CI installs with --locked.
```

- The `cli-install` job (`ci.yml:60-82`) uses `uv tool install ./apps/cli`, which does not use the workspace lock — leave it.
- The lock is in sync at planning time: `uv lock --check` exits 0 ("Resolved 180 packages").

uv semantics: `uv sync --locked` asserts the lockfile is up to date and errors
if it would change; `uv sync --frozen` uses the lockfile without checking;
`uv lock --check` only checks.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Lock is current | `uv lock --check` | exit 0 |
| Install as CI will | `uv sync --locked` | exit 0 |
| Workflow file is valid YAML | `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"` | `ok` (if PyYAML is missing, use `uv run python -c …`) |
| Format check | `pnpm format:check` | exit 0 (Prettier checks YAML) |

## Scope

**In scope**:

- `.github/workflows/ci.yml` (the two `uv sync` lines only)
- `CLAUDE.md` — one line in its "Commands" block (see Step 3)

**Out of scope** (do NOT touch):

- `deploy/backend.Dockerfile` — `--frozen` is right there once CI guarantees the lock is current (the image build should not re-resolve).
- `scripts/release.py` — its comment becomes true; no edit needed.
- `uv.lock` and every `pyproject.toml` — this plan changes no dependency. If `uv lock --check` fails, that is a STOP condition, not something to fix by re-locking.
- The `cli-install` job, the other workflows, pytest parallelism, caching.
- `CHANGELOG.md` — nothing changes for people who use dotrix.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/010-ci-uv-locked origin/stage`. PRs go into `stage`, never `main`.
- Commit message: one short sentence-case line (e.g. `CI: install Python with --locked, so a stale uv.lock fails`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Confirm the lock is current before changing CI

**Verify**: `uv lock --check` → exit 0. If it exits non-zero, STOP: the lock is
already stale on this branch and someone must run `uv lock` deliberately first.

### Step 2: Use `--locked` in CI

In `.github/workflows/ci.yml` change both occurrences of

```yaml
      - run: uv sync
```

to

```yaml
      - name: Install Python packages (run `uv lock` if this fails)
        run: uv sync --locked
```

matching the style of the neighbouring named steps (e.g.
`- name: OpenAPI schema is up to date (run \`pnpm openapi\` if this fails)`).

**Verify**:
- `grep -n "uv sync" .github/workflows/ci.yml` → exactly two lines, both `uv sync --locked`
- the YAML check from the table prints `ok`
- `uv sync --locked` → exit 0 locally

### Step 3: Tell contributors

In `CLAUDE.md`, in the "Commands" code block, the first line is:

```bash
uv sync                                   # install all Python packages
```

Add directly under it:

```bash
uv lock                                   # after changing any pyproject.toml: CI installs with --locked and fails on a stale uv.lock
```

Keep the column alignment of the comments as in the surrounding lines.

**Verify**: `grep -n "uv lock" CLAUDE.md` → one new line in the Commands block

### Step 4: Prove the check bites (local, then undo)

1. In `apps/cli/pyproject.toml`, temporarily add a harmless dependency to the
   `dependencies` list, e.g. `"tomli>=2"`.
2. Run `uv lock --check` → it must exit **non-zero** (the lock is now stale).
3. Undo the edit with `git checkout -- apps/cli/pyproject.toml`.
4. Run `uv lock --check` → exit 0, and `git status --short` shows no change to
   `uv.lock` or any `pyproject.toml`.

**Verify**: steps 2 and 4 behave as stated. If step 2 exits 0, STOP: `--locked`
would not catch a stale lock in this setup and the plan's premise is wrong.

### Step 5: Format

**Verify**: `pnpm format:check` → exit 0

## Test plan

No unit tests: the change is CI configuration. The proof is Step 4 (a stale
lock is detected) plus the first CI run on the pull request (the `python` and
`e2e` jobs must still pass with `--locked`).

## Done criteria

- [ ] `grep -c "uv sync --locked" .github/workflows/ci.yml` → 2, and `grep -c "run: uv sync$" .github/workflows/ci.yml` → 0
- [ ] `uv lock --check` exits 0 and `uv sync --locked` exits 0
- [ ] `git status --short` shows only `.github/workflows/ci.yml` and `CLAUDE.md` (no `uv.lock`, no `pyproject.toml`)
- [ ] `pnpm format:check` exits 0
- [ ] `plans/README.md` status row updated

## STOP conditions

- The excerpts in "Current state" do not match the live files.
- `uv lock --check` fails before you change anything.
- Step 4's negative check does not fail as expected.
- After the change, CI's `python` or `e2e` job fails at the install step on a branch whose lock you verified locally — report the CI log; a uv version difference between local and `astral-sh/setup-uv@v6` is the likely cause and pinning uv's version is a decision for the maintainer.

## Maintenance notes

- From now on a dependency change needs `uv lock` in the same pull request. The release script already runs `uv lock` when it bumps versions.
- Related, not done here: the `python` job (about 9.5 minutes at the last observed run) is CI's slowest step; running pytest in parallel (`pytest-xdist`) is a separate change that needs a per-worker Redis database.
- Related, not done here: there is no Dependabot or Renovate configuration, and third-party GitHub Actions are pinned by tag rather than by commit.
