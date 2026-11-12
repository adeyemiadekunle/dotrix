# Plan 034: A session's sandbox is closed when the check before reusing it fails

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 7fb2b01..HEAD -- apps/backend/src/dotrix_backend/modules/coding/runner.py apps/backend/src/dotrix_backend/modules/coding/warm.py`
> If any of these changed, compare the "Current state" excerpts against the
> live code; on a mismatch in the lines this plan changes, treat it as a STOP
> condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `7fb2b01`, 2026-11-12

## Why this matters

Between turns a coding session keeps its sandbox (a container or a cloud
microVM) so the next turn starts fast. When the next turn takes it out of the
pool, it first checks that its files still match the branch. If that check
itself fails with an exception (the container is gone, the Docker daemon or the
cloud API times out, the host checkout can't be read), the sandbox has already
left the pool and nothing closes it: it keeps running until some outer sweep
notices, holding memory on the worker or billed time in the cloud.

## Current state

`apps/backend/src/dotrix_backend/modules/coding/runner.py` (lines ~500-520):

```python
        box = await self.pool.take(session_id, credential)
        woken = False
        if box is None and sleeping is not None:
            box = await self._wake(session_id, sleeping, slept_at, credential, tool, key)
            woken = box is not None
        warm = False
        if box is not None:
            here = await box.exec(["git", "rev-parse", "HEAD^{tree}"], timeout=60)
            warm = here.code == 0 and here.stdout.strip() == (await run_git(host, "rev-parse", "HEAD^{tree}")).strip()
            if not warm:
                await close_quietly(box)
                box = None
        resumed = warm and resumable
        if box is None:
            copy = work / "upload" / "repo"
            await _export(host, copy)
            await _baseline(copy)
            box = await self.sandbox.open(run_id, copy, tool, key, **({"allow": allow} if allow else {}))
            if resumable and transcript_key:
                resumed = await self._restore_transcript(box, tool, claude_session, transcript_key)
        keep = False
        reported: float | None = None
        try:
```

`box.exec` and `run_git` can both raise. The `try:` that guarantees the box is
closed or returned to the pool starts only after this block. Between
`self.sandbox.open(...)` and that `try:`, `_restore_transcript` can raise too.

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

- `apps/backend/src/dotrix_backend/modules/coding/runner.py` (this block only)
- `apps/backend/tests/integration/test_coding.py` or the warm-pool tests beside it
- `CHANGELOG.md` (one line under Unreleased, in the existing section of its kind; never add a second heading)

**Out of scope** (do NOT touch):

- `warm.py`'s pool and reaper.
- The sandbox implementations.

## Git workflow

- Work on the branch the reviewer gives you. Otherwise branch from `stage` and open the PR into `stage`, never `main`.
- Commit messages: one short sentence-case line.
- Do NOT push or open a PR unless instructed. Never use bare `git stash`.

## Steps

### Step 1: A failed check means "not warm", and the box is closed

Wrap the two-line check in `try/except Exception`: on any exception, log a warning with the run id, treat it as `warm = False`, and fall into the existing `close_quietly(box); box = None` path, so the turn carries on with a fresh sandbox. Don't catch `asyncio.CancelledError` as a failure: on cancellation close the box and re-raise.

### Step 2: Nothing between opening a box and the `try:` can leak it

Move `_restore_transcript` inside the protected region, or guard it the same way: if it raises, close the freshly opened box and re-raise. Read from `self.sandbox.open(` down to the `try:` and make sure every awaited call between them is covered; list them in your report.

### Step 3: Changelog

Under Unreleased → Fixed: `- A coding session's sandbox is shut down when it can't be checked for reuse, and the turn starts in a fresh one.`

## Test plan

Using the fake sandbox and pool the coding tests already use:

1. A warm box whose `exec` raises `RuntimeError` on `git rev-parse`: the turn completes in a fresh sandbox, and the old box's `close` was called once.
2. A warm box whose check returns a different tree still closes it and opens a fresh one (existing behaviour; add only if not already covered).
3. A fresh box whose transcript restore raises: the box is closed and the turn fails with that error.

Every new test must fail on the code before your change. Check that (a temporary WIP commit, then the old source checked out) and say how in your report.

## Done criteria

- [ ] Tests 1 and 3 failed before the change and pass now
- [ ] `uv run pytest apps/backend/tests/integration/test_coding.py -q` passes
- [ ] ruff clean; release check exit 0
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` status row updated (unless the reviewer maintains it)

## STOP conditions

- The block no longer matches the excerpt.
- Closing the box on a failed check would discard a sleeping cloud sandbox that `_wake` expects to keep (say what `_wake` needs).

## Maintenance notes

- Any new awaited call added between taking or opening a box and the `try:` needs the same guard; consider moving the whole acquisition into a helper that owns cleanup if this block grows.
