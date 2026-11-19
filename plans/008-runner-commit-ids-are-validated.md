# Plan 008: A commit ID reported by a local runner must be a 40-character hex string before git sees it

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat f477722..HEAD -- apps/backend/src/dotrix_backend/modules/coding/schemas.py apps/backend/src/dotrix_backend/modules/coding/files.py`
> If either file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `f477722`, 2026-11-11

## Why this matters

A person's computer can code a turn locally (`dotrix runner`). The runner tells
the platform which commit the turn started from (`base_sha`) in its heartbeat
and result. The API accepts any 40-character string, stores it on the run, and
later passes it as a bare positional argument to `git fetch`, `git read-tree`
and `git diff-tree` in the server's shared checkout when someone opens the
turn's Files or Changes view. A value beginning with `-` would be read by git
as an option. No working exploit was demonstrated within 40 characters, but
real values are always lowercase hex, so validating them is free and closes
the class of problem. After this plan a non-hex value is rejected at the API
and, defensively, refused again before any git command.

## Current state

- `apps/backend/src/dotrix_backend/modules/coding/schemas.py:269-292` — the runner payloads:

```python
class RunnerHeartbeat(BaseModel):
    lease_token: int
    events: list[RunnerEvent] = Field(default_factory=list, max_length=200)
    base_sha: str | None = Field(default=None, min_length=40, max_length=40)
    worktree: str | None = Field(default=None, max_length=1024, description="The turn's worktree on this computer")
...
class RunnerResult(BaseModel):
    lease_token: int
    outcome: Literal["changes", "no_changes", "failed", "stopped"]
    patch: str | None = Field(default=None, max_length=20_000_000, description="`git diff --cached --binary` against base_sha")
    base_sha: str | None = Field(default=None, min_length=40, max_length=40)
```

- `apps/backend/src/dotrix_backend/modules/coding/local.py:169-170` — stored as given:

```python
        if data.base_sha:
            run.base_sha = data.base_sha
```

- `apps/backend/src/dotrix_backend/modules/coding/files.py` — a turn's files. `_prepared` (lines 98-119) is the single entry point every read goes through:

```python
    async def _prepared(self, run: CodingRun) -> tuple[Path, str, str]:
        """The checkout, the turn's base commit (in it), and the tree the turn leaves."""
        if self.checkouts is None:
            raise TurnFilesUnavailable("Reading code isn't set up on this server")
        if not run.base_sha:
            raise TurnFilesUnavailable("The turn hasn't started on a commit yet")
        checkout = await CodeService(self.session, self.checkouts).ensure(run.workspace_id, run.project_id)
```

  and the git calls that receive it, e.g. `files.py:140`:

```python
        await run_git(root, "fetch", "-q", "--depth", "1", "--no-tags", "--no-write-fetch-head", url, run.base_sha,
                      env=auth_env(url, token), timeout=FETCH_TIMEOUT)
```

  and `files.py:167`: `await run_git(root, "read-tree", base, env=env)`.

- The local runner sends `git rev-parse` output (lowercase hex), see `apps/cli/src/dotrix_cli/runner.py`. Repositories here use SHA-1 object names (40 characters), which the existing `min_length=40, max_length=40` already assumes.

Conventions: Pydantic v2 `Field(..., pattern=...)`; after any API schema
change run `pnpm openapi` and commit `packages/api-client/openapi.json` and
`packages/api-client/src/schema.ts` (CI checks they are current). Domain errors
are raised as exceptions (`TurnFilesUnavailable` is already used in this file).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync && pnpm install` | exit 0 |
| Local services | `pnpm db:up` | Postgres running |
| Unit tests | `uv run pytest apps/backend/tests/unit/test_coding.py -q` | all pass |
| Coding integration tests | `uv run pytest apps/backend/tests/integration/test_coding.py -q` | all pass |
| Lint | `uv run ruff check apps packages` | exit 0 |
| Regenerate schema + client | `pnpm openapi` | exit 0 |
| TS checks | `pnpm typecheck && pnpm format:check` | exit 0 |

## Scope

**In scope**:

- `apps/backend/src/dotrix_backend/modules/coding/schemas.py`
- `apps/backend/src/dotrix_backend/modules/coding/files.py`
- `apps/backend/tests/unit/test_coding.py` (add tests)
- `packages/api-client/openapi.json`, `packages/api-client/src/schema.ts` (generated by `pnpm openapi` only)
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- `modules/coding/runner.py` (the cloud worker sets `base_sha` itself from the real checkout) and `modules/coding/local.py` (validation happens in the schema before it runs).
- `modules/code/checkouts.py` `run_git` — do not change how git is invoked globally.
- The CLI (`apps/cli`) — it already sends valid values.
- Existing rows: no data migration. A stored bad value is handled by the guard in `files.py`.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/008-validate-base-sha origin/stage`. PRs go into `stage`, never `main`.
- Commit message: one short sentence-case line (e.g. `Local runners: a turn's base commit must be a full hex commit ID`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Validate in the schema

In `modules/coding/schemas.py`, near the top-level constants (or just above
`class RunnerHeartbeat`), add:

```python
COMMIT_SHA = r"^[0-9a-f]{40}$"  # a full commit ID, as `git rev-parse` prints it
```

and change both fields to:

```python
    base_sha: str | None = Field(default=None, pattern=COMMIT_SHA)
```

(the pattern makes `min_length`/`max_length` redundant; remove them).

**Verify**: `uv run python -c "from dotrix_backend.modules.coding.schemas import RunnerHeartbeat; RunnerHeartbeat(lease_token=1, base_sha='a'*40); print('ok')"` → `ok`

### Step 2: Refuse a non-hex value before any git command

In `modules/coding/files.py`, add `import re` if missing, import `COMMIT_SHA`
from `.schemas` (if that creates a circular import, define the same compiled
regex locally with a comment pointing at `schemas.COMMIT_SHA`), and in
`_prepared`, directly after the `if not run.base_sha:` check, add:

```python
        if not re.fullmatch(COMMIT_SHA, run.base_sha):
            # Never hand git something that isn't a commit ID (a run recorded before this was checked).
            raise TurnFilesUnavailable("The turn's base commit isn't a valid commit ID")
```

Then confirm `_prepared` really is the only way into the git calls:
`grep -n "base_sha" apps/backend/src/dotrix_backend/modules/coding/files.py`.
Every use other than building a response object (`CodingDiff(base_sha=…)`)
must be reached through `_prepared`. If a method uses `run.base_sha` in a git
call without going through `_prepared`, add the same guard there.

**Verify**: `uv run ruff check apps/backend` → exit 0

### Step 3: Unit tests

In `apps/backend/tests/unit/test_coding.py` add (plain functions; import
`pytest`, `ValidationError` from `pydantic`, and the two schema classes):

1. `test_a_runner_base_commit_must_be_a_full_hex_id`: for each of
   `"-" + "a" * 39`, `"A" * 40`, `"g" * 40`, `"a" * 39`, `"a" * 41`,
   `"--upload-pack=" + "x" * 26` — both `RunnerHeartbeat(lease_token=1, base_sha=value)`
   and `RunnerResult(lease_token=1, outcome="no_changes", base_sha=value)`
   raise `ValidationError`.
2. `test_a_runner_base_commit_accepts_a_real_id_or_none`: `"0123456789abcdef0123456789abcdef01234567"` and `None` are accepted by both classes.

**Verify**: `uv run pytest apps/backend/tests/unit/test_coding.py -q` → all pass, including 2 new tests

### Step 4: Regenerate the API schema and run the coding suite

Run `pnpm openapi`.

**Verify**:
- `git diff --stat packages/api-client` → `openapi.json` and `src/schema.ts` changed (the `base_sha` properties now carry the pattern)
- `uv run pytest apps/backend/tests/integration/test_coding.py -q` → all pass (the local-runner tests there send real commit IDs)
- `pnpm typecheck && pnpm format:check` → exit 0

### Step 5: Changelog

Under `## [Unreleased]` → `### Security` in `CHANGELOG.md` add:
`- A computer coding a turn locally can only report a full commit ID as the turn's starting point; anything else is refused.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- Two new unit tests in `tests/unit/test_coding.py` (Step 3).
- Regression: `tests/integration/test_coding.py` local-runner tests (`test_a_local_turn_…`) pass unchanged.

## Done criteria

- [ ] `uv run pytest apps/backend/tests/unit/test_coding.py apps/backend/tests/integration/test_coding.py -q` exits 0
- [ ] `uv run ruff check apps packages` exits 0
- [ ] `uv run python apps/backend/scripts/export_openapi.py && git diff --exit-code packages/api-client/openapi.json` exits 0
- [ ] `grep -n "min_length=40" apps/backend/src/dotrix_backend/modules/coding/schemas.py` returns nothing for the two `base_sha` fields
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

- The excerpts in "Current state" do not match the live code.
- A test in `test_coding.py` sends a `base_sha` that is not lowercase 40-hex and legitimately should be accepted (for example an uppercase ID from a fake): report it instead of loosening the pattern.
- You find evidence the product supports SHA-256 repositories (64-character IDs) — report; the pattern would need `{40}|{64}` and that is a decision.

## Maintenance notes

- Other places that pass stored revisions to git (`commit_sha`, branch names) were not audited in this plan. Branch names come from the platform, not the runner; a reviewer may want a follow-up that adds `--end-of-options` before revision arguments in `modules/coding/files.py` where the installed git supports it.
- If runners ever report other git identifiers, give them the same `pattern=` treatment at the schema.
