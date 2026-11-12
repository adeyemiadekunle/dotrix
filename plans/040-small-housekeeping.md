# Plan 040: Housekeeping: the stray Redis dump, the seroval advisories, and the documented CLI install

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 7fb2b01..HEAD -- dump.rdb .gitignore package.json pnpm-lock.yaml README.md apps/cli/pyproject.toml`
> If any of these changed, compare the "Current state" excerpts against the
> live code; on a mismatch in the lines this plan changes, treat it as a STOP
> condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: hygiene
- **Planned at**: commit `7fb2b01`, 2026-11-12

## Why this matters

Three small things from the audit, each minutes of work:

1. A Redis snapshot (`dump.rdb`) is committed at the repository root and isn't
   ignored, so a local Redis started from the root keeps rewriting a tracked
   file, and it may hold local data.
2. `pnpm audit --prod` reported two moderate advisories in `seroval`, pulled in
   by `@tanstack/react-router`.
3. The README tells people to install the CLI with `pipx`, but the CLI depends
   on `dotrix-engine`, which isn't on PyPI, so the documented command can't
   resolve its dependencies.

## Current state

- `git ls-files dump.rdb` prints `dump.rdb`; `.gitignore` has no entry for it.
- `README.md:217` (the `pipx` line) and `apps/cli/pyproject.toml:7,18` (the name and the `dotrix-engine` dependency). The supported installs today are the repository checkout (`uv sync`) and the standalone CLI built by `apps/cli/scripts/standalone.py`, attached to each GitHub release by `.github/workflows/desktop.yml`.
- Run `pnpm audit --prod` first: the advisories and the fixed versions may have changed since the audit.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Audit | `pnpm audit --prod` | no seroval advisory |
| Build and tests | `pnpm build && pnpm typecheck && pnpm test` | pass |
| Format | `pnpm format:check` | exit 0 |

Integration tests need Postgres and Redis (`pnpm db:up`) and the `DOTRIX_*` test variables described in `CLAUDE.md`.

## Scope

**In scope**:

- `dump.rdb` (deleted), `.gitignore`
- `package.json` / `apps/*/package.json` / `pnpm-lock.yaml` for the router bump or an override
- `README.md` (the install section only)
- `CHANGELOG.md` (one line under Unreleased, in the existing section of its kind; never add a second heading)

**Out of scope** (do NOT touch):

- Publishing anything to PyPI.
- Rewriting git history to purge the old dump.
- Any dependency other than the router and `seroval`.

## Git workflow

- Work on the branch the reviewer gives you. Otherwise branch from `stage` and open the PR into `stage`, never `main`.
- Commit messages: one short sentence-case line.
- Do NOT push or open a PR unless instructed. Never use bare `git stash`.

## Steps

### Step 1: The dump

Look at it before deleting: `strings dump.rdb | head -50`. If it holds anything that looks like a token, key or personal data, STOP and report (history then needs cleaning and the secret rotating, which is the owner's call). Otherwise `git rm dump.rdb` and add `dump.rdb` and `*.rdb` to `.gitignore`.

### Step 2: seroval

`pnpm audit --prod`. If a patch or minor release of `@tanstack/react-router` (and its companion packages at the same version) resolves it, bump them together. Otherwise add a `pnpm.overrides` entry for `seroval` at the fixed version in the root `package.json`, with the advisory ids in the commit message. `pnpm install`, then `pnpm build && pnpm typecheck && pnpm test`.

**Verify**: `pnpm audit --prod` no longer lists `seroval`.

### Step 3: The README's install line

Replace the `pipx` instruction with what works: download the standalone CLI from the latest GitHub release, or run it from a checkout with `uv run dotrix`. Keep the section short. Do not change `apps/cli/pyproject.toml`.

### Step 4: Changelog

Under Unreleased → Fixed: `- The README's CLI install instructions now describe installs that work (the release download, or a checkout).` and, if a dependency changed, under Security: `- Updated a routing dependency for two moderate advisories.`

## Test plan

No new tests. `pnpm build`, `pnpm typecheck`, `pnpm test` and `pnpm knip` must pass after Step 2; the browser tests run in CI.

Every new test must fail on the code before your change. Check that (a temporary WIP commit, then the old source checked out) and say how in your report.

## Done criteria

- [ ] `git ls-files dump.rdb` prints nothing and `.gitignore` covers it
- [ ] `pnpm audit --prod` shows no `seroval` advisory
- [ ] `grep -n pipx README.md` finds no instruction that can't work
- [ ] `pnpm build && pnpm typecheck && pnpm test` pass; `pnpm format:check` exit 0
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` status row updated (unless the reviewer maintains it)

## STOP conditions

- The dump contains a secret or personal data.
- Fixing `seroval` needs a major router upgrade.

## Maintenance notes

- If the CLI should be installable with `pipx`, the engine has to be published or vendored into the CLI's wheel; that is a release decision, not housekeeping.
