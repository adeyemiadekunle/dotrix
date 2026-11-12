# Plan 031: A coding turn's patch is stored and pushed byte for byte, whatever its files' encoding

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git log --oneline -1 -- apps/backend/src/dotrix_backend/modules/coding apps/cli/src/dotrix_cli/runner.py`
> and compare the "Current state" excerpts below against the live code. On a
> mismatch in the lines this plan changes, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MEDIUM (a migration on `coding_runs`, and the publish path)
- **Depends on**: 029 (done, re-scoped)
- **Category**: correctness
- **Planned at**: 2026-11-12, after plan 029 landed on `claude/bold-darwin-bfgpdy`

## Why this matters

Plan 029 set out to send a local turn's patch byte for byte. It found that the
platform stores a patch in a Postgres `text` column (`coding_runs.pending_patch`,
and `coding_runs.diff`), and Postgres text can't hold bytes that aren't valid
UTF-8. Python's reversible `surrogateescape` decoding is refused by asyncpg
("surrogates not allowed"), which was the plan's STOP condition.

So 029 shipped the safe half: a local turn whose patch isn't UTF-8 (a Latin-1
source file, say) now **fails with a clear reason** ("A changed file isn't
UTF-8 text, so the changes can't be sent exactly yet; nothing was sent. The
worktree keeps them."). Before 029 it was sent decoded with `errors="replace"`,
silently writing U+FFFD into the person's files.

This plan finishes the job: such a turn's changes are stored as exact bytes and
pushed unchanged, for local and cloud turns alike. The people it helps work in
repositories with legacy-encoded files (Latin-1, Shift-JIS, Windows-1252
source, `.properties` files).

## Current state

- `apps/backend/src/dotrix_backend/modules/coding/models.py:146`:
  `pending_patch: Mapped[str | None] = mapped_column(Text, deferred=True)`.
  `diff` (a few lines below, also `Text`) is what Changes and Files show.
- Writers:
  - `coding/runner.py:1138` (`ready_for_acceptance`): `run.status, run.pending_patch, run.diff, run.files_changed = CodingRunStatus.CHANGES_READY, diff, diff, files`
  - `coding/local.py:220`: `run.pending_patch, run.files_changed, run.summary = patch, files, summary or run.summary` (a local runner's result, `RunnerResult.patch: str`)
  - Cleared to `None` at `coding/service.py:495`, `:596` and `coding/runner.py:1170`.
- Readers: `coding/runner.py:431` (the publish-only pass reads `pending_patch` and applies it), the `_stage` helper around `runner.py:649` and `:710`, and `coding/files.py:94`, `:112`, `:174` (a turn's diff, tree and file views).
- The CLI runner (`apps/cli/src/dotrix_cli/runner.py`) since 029: `git_bytes(...)` returns the patch as bytes; `patch = raw_patch.decode("utf-8")`, and on `UnicodeDecodeError` the turn is reported `failed` with the reason above.
- Cloud turns build their patch in the worker (`coding/runner.py`); check how it is read from git there (`decode(errors="replace")` or not) as part of Step 1.

## Scope

**In scope**:

- `apps/backend/src/dotrix_backend/modules/coding/{models,runner,local,files,schemas,service}.py`
- A new Alembic migration under `apps/backend/migrations/versions/`
- `apps/cli/src/dotrix_cli/runner.py` (send the bytes) and its tests
- Tests: `apps/backend/tests/integration/test_coding.py`, `test_coding_local.py` (or wherever local results are tested), `apps/cli/tests/test_runner.py`
- `packages/api-client/openapi.json` and `src/schema.ts` (via `pnpm openapi`), `CHANGELOG.md`

**Out of scope**: the web's diff rendering (it keeps reading `diff` text); the Juno review, which reads the diff as text; GitHub publication beyond applying the exact patch.

## Steps

### Step 1: Find every path a patch takes

List each place a patch is produced, stored, read or applied, cloud and local:
`grep -rn "pending_patch\|\.diff\b\|git_bytes\|decode(errors" apps/backend/src/dotrix_backend/modules/coding apps/cli/src/dotrix_cli/runner.py`.
Write the list into your report. **Verify**: every reader in "Current state" is on it; anything not on it is either added to the steps below or named as a STOP.

### Step 2: Store the exact bytes

- Add `pending_patch_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)` to `CodingRun`. Keep `pending_patch` (text) for rows written before this migration; new rows write only the bytes column and leave `pending_patch` `None`.
- A helper `patch_of(run) -> bytes | None` returns `pending_patch_bytes`, else `pending_patch.encode()`, so old waiting turns still publish. Every reader from Step 1 that applies a patch uses it.
- `run.diff` (what people see) becomes `patch.decode("utf-8", errors="replace")`: lossy on purpose, shown only.
- Every place that clears `pending_patch` clears both columns.
- Migration: `pnpm db:revision "coding patches as bytes"`, adding the nullable column only (no data copy: the helper reads old rows). **Verify**: `uv run alembic -c apps/backend/alembic.ini check` reports no difference.

### Step 3: Apply bytes, not text

Where the worker applies a patch (`git apply` in the publish-only pass and `_stage`), feed the bytes on stdin or write them to a file in binary mode. Size checks and `git apply --numstat` run on the bytes. Cloud turns read their patch from git as bytes too (no `decode(errors="replace")` on the way to storage).

### Step 4: The local runner sends bytes

- `RunnerResult` gains `patch_b64: str | None`. The API decodes it to bytes; when both are given, `patch_b64` wins. `patch` (text) stays accepted from older runners.
- The CLI runner sends `patch_b64` always. Remove 029's "isn't UTF-8 text" refusal; keep the event flush and the 2,000-step cap untouched.
- An older API ignores `patch_b64` (pydantic's default `extra="ignore"`) and would see no patch: also send `patch` when the bytes decode as UTF-8, so a new runner still works against an older platform for UTF-8 changes.
- `pnpm openapi`, and commit `openapi.json` and `schema.ts`.

### Step 5: Tests

- Integration: a local result whose patch holds `b"caf\xe9\n"` (Latin-1) is stored, accepted, and the publish-only pass's applied tree has those exact bytes (`git cat-file -p` on the pushed blob, or the working file read in binary).
- Integration: a turn waiting since before the migration (`pending_patch` text set, bytes `None`) still publishes.
- Cloud: a worker turn that changes a Latin-1 file keeps its bytes (use the scripted engine the existing coding tests use).
- CLI: a Latin-1 change is sent as `patch_b64` that decodes to the exact bytes; a UTF-8 change sends both fields.
- Each new test fails on the code before this plan. Say so in the report.

### Step 6: Changelog

Under Unreleased → Fixed: `- Kai's changes to files that aren't UTF-8 text (older encodings such as Latin-1) are now kept and pushed exactly, from cloud and local turns.`

## Done criteria

- [ ] `uv run pytest apps/backend/tests/integration/test_coding.py apps/cli/tests -q` passes, with the new tests
- [ ] `uv run alembic -c apps/backend/alembic.ini check` clean; `uv run ruff check apps packages` clean
- [ ] `pnpm openapi` leaves no diff after commit; `python scripts/release.py check` exit 0
- [ ] `grep -n "isn't UTF-8 text" apps/cli/src/dotrix_cli/runner.py` finds nothing
- [ ] `plans/README.md` status row updated

## STOP conditions

- A reader from Step 1 needs the patch as text for something other than display (say so, with the line).
- `git apply` in the sandbox (Docker or Docker Cloud) is fed through a text-only channel you can't switch to bytes without changing `sandbox.py` or `docker_cloud.py`.
- The migration would need to copy or rewrite existing rows.

## Maintenance notes

- `diff` stays lossy text for display; anything that writes files must use `patch_of(run)`.
- `pending_patch` (text) can be dropped in a later release once no turn written before this migration can still be waiting (`changes_ready` turns are short-lived; check the table first).
