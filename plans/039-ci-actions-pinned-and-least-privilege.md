# Plan 039: CI's third-party actions are pinned to commits, and pull-request builds can't write to the repository

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 7fb2b01..HEAD -- .github/workflows`
> If any of these changed, compare the "Current state" excerpts against the
> live code; on a mismatch in the lines this plan changes, treat it as a STOP
> condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `7fb2b01`, 2026-11-12

## Why this matters

Two supply-chain gaps in the workflows:

1. Every action is referenced by a moving tag (`actions/checkout@v4`,
   `astral-sh/setup-uv@v6`, `pnpm/action-setup@v4`, `docker/build-push-action@v6`, ...).
   Whoever controls one of those repositories, or compromises it, can move the
   tag and run their code in this repository's CI with its token and secrets.
   That has happened to widely used actions.
2. `desktop.yml` sets `permissions: contents: write` for the whole workflow,
   and the workflow also runs on pull requests that touch the desktop app or
   the CLI. The write permission is needed only to attach builds to a release.

## Current state

`grep -n "uses:" .github/workflows/*.yml` at this commit: `actions/checkout@v4` (8), `astral-sh/setup-uv@v6` (4), `actions/setup-node@v4` (4), `pnpm/action-setup@v4` (3), `actions/upload-artifact@v4` (2), `docker/setup-buildx-action@v3`, `docker/login-action@v3`, `docker/build-push-action@v6`.

`.github/workflows/desktop.yml`:

```yaml
on:
  release:
    types: [published]
  pull_request:
    paths:
      - apps/desktop/**
      - apps/cli/**
      - CHANGELOG.md
      - .github/workflows/desktop.yml

permissions:
  contents: write # attaching the builds to the release
```

Read each workflow's top-level and job-level `permissions` (`grep -n "permissions:" -A4 .github/workflows/*.yml`); a workflow with none gets the repository default.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend tests | `uv run pytest apps/backend/tests -q -k "<the tests you add>"` | pass |
| Lint | `uv run ruff check apps packages` | All checks passed |
| Release check | `python scripts/release.py check` | exit 0 |
| Format | `pnpm format:check` | exit 0 |

Integration tests need Postgres and Redis (`pnpm db:up`) and the `DOTRIX_*` test variables described in `CLAUDE.md`.

## Scope

**In scope**:

- `.github/workflows/*.yml`
- `.github/dependabot.yml` (create or extend)
- `CHANGELOG.md` (one line under Unreleased, in the existing section of its kind; never add a second heading)

**Out of scope** (do NOT touch):

- What the workflows build and test.
- Repository settings on GitHub (noted for the owner in Maintenance).

## Git workflow

- Work on the branch the reviewer gives you. Otherwise branch from `stage` and open the PR into `stage`, never `main`.
- Commit messages: one short sentence-case line.
- Do NOT push or open a PR unless instructed. Never use bare `git stash`.

## Steps

### Step 1: Pin every action to a commit

For each `uses: owner/name@tag`, resolve the tag to its commit SHA and write `uses: owner/name@<40-char sha> # vX.Y.Z` (the exact release the tag points at today, in the comment). Resolve with `git ls-remote https://github.com/owner/name refs/tags/<tag>` (for an annotated tag use the `^{}` line). If the network doesn't allow that, STOP and report; do not guess a SHA.

**Verify**: `grep -n "uses:" .github/workflows/*.yml | grep -v "@[0-9a-f]\{40\}"` prints nothing (local `./` actions excepted).

### Step 2: Keep them current

In `.github/dependabot.yml`, add (or extend) a `github-actions` ecosystem entry for directory `/`, weekly, targeting the `stage` branch, with updates grouped into one pull request. Leave any existing entries as they are.

### Step 3: Least privilege

- `desktop.yml`: top-level `permissions: contents: read`. Give `contents: write` only to the job (or step's job) that uploads to the release, and make sure that job, or the upload step, runs only `if: github.event_name == 'release'`. Read the file to see whether the upload already has that condition.
- Every other workflow: if it has no `permissions` block, add a top-level one with the least it needs (`contents: read` for CI; `release.yml` needs `contents: write` to tag and publish; `coding-image.yml` needs `packages: write` if it pushes to GHCR). State each in the report with the reason.

### Step 4: Changelog

No user-facing change: add nothing to `CHANGELOG.md` unless the repo's rule requires a line for every PR, in which case under Security: `- CI's build steps are pinned to exact versions and run with the least access they need.`

## Test plan

There is no test harness for workflows. Check by:

- the `grep` in Step 1;
- `python - <<'EOF'` loading every workflow with `yaml.safe_load` to confirm each still parses;
- if `actionlint` is available, run it; if not, say so.

CI on the pull request is the real test: every workflow that runs on PRs must stay green, and the desktop PR build must still produce its artifacts with read-only contents.

Every new test must fail on the code before your change. Check that (a temporary WIP commit, then the old source checked out) and say how in your report.

## Done criteria

- [ ] Every `uses:` is a 40-character SHA with its version in a comment
- [ ] `desktop.yml` grants `contents: write` only where a release is being published
- [ ] every workflow has an explicit `permissions` block
- [ ] all workflow files parse as YAML; `pnpm format:check` exit 0
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` status row updated (unless the reviewer maintains it)

## STOP conditions

- A tag can't be resolved from here.
- A job needs a permission you can't determine from the file (name the step).
- A workflow uses `pull_request_target` or checks out PR code with a write token (report it: that is a separate, more serious finding).

## Maintenance notes

- (owner) In the repository's Actions settings, set the default workflow permissions to read-only, so a new workflow without a block is safe by default.
- Dependabot's PRs for actions go to `stage` like everything else.
