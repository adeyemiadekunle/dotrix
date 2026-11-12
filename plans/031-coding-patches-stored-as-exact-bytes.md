# Plan 031: A coding turn's patch is kept and pushed byte for byte, whatever its files' encoding

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 8690469..HEAD -- apps/backend/src/dotrix_backend/modules/coding apps/backend/src/dotrix_backend/modules/code/checkouts.py apps/cli/src/dotrix_cli/runner.py`
> If any of these changed, compare the "Current state" excerpts against the
> live code; on a mismatch in the lines this plan changes, treat it as a STOP
> condition.

## Status

- **Priority**: P1 (cloud turns corrupt such files silently today)
- **Effort**: M
- **Risk**: MEDIUM (a migration on `coding_runs`; the path every pushed change takes)
- **Depends on**: 029 (done, re-scoped)
- **Category**: correctness
- **Planned at**: commit `8690469`, 2026-11-12

## Why this matters

When Kai changes a file that isn't UTF-8 text (Latin-1, Windows-1252,
Shift-JIS: older Java `.properties` files, legacy C and PHP source), the change
has to reach GitHub exactly as Kai wrote it. Today it doesn't:

- **Cloud turns (silent corruption).** The sandbox returns the turn's diff as a
  `str` decoded with `errors="replace"`. Every byte that isn't UTF-8 becomes
  U+FFFD, and that damaged patch is what gets applied, committed and pushed. The
  PR then changes characters the agent never touched. Nobody is told.
- **Local turns (refused since plan 029).** The runner now ends such a turn as
  failed ("A changed file isn't UTF-8 text, so the changes can't be sent exactly
  yet") instead of sending a damaged patch. That is safe, but the person can't
  use Kai on those files.

The root cause is the same in both: the patch is carried as text and stored
in Postgres `text` columns (`coding_runs.pending_patch`, `coding_runs.diff`).
Postgres text can't hold invalid UTF-8, and Python's reversible
`surrogateescape` is refused by asyncpg ("surrogates not allowed"). Plan 029
confirmed that.

After this plan, the patch is bytes from the moment git writes it to the moment
git applies it. Only the copy people *see* (`diff`) is decoded, lossily, for
display.

## Current state

The patch's path, every step (lines at `8690469`):

1. **Produced in a cloud sandbox.** `coding/runner.py:530-545`:

   ```python
   changes = await box.exec(
       ["sh", "-c", "git add -A && git -c core.quotepath=off diff --cached --binary --no-color "
        f"--no-ext-diff --no-textconv --no-renames {baseline}"],
       timeout=300,
   )
   ...
   if changes.truncated or len(changes.stdout.encode()) > guard.MAX_PATCH_BYTES:
       raise RunFailed(...)
   ...
   paths, files = await _stage(work, host, changes.stdout)
   ```

   `box.exec` returns `ExecResult` (`coding/sandbox.py:64`):

   ```python
   class ExecResult:
       code: int | None
       stdout: str
       stderr: str
       timed_out: bool = False
       cancelled: bool = False
       truncated: bool = False
   ```

   Every implementation keeps raw `bytes` and decodes them with
   `errors="replace"` when it builds the result: `sandbox.py:187` and
   `sandbox.py:263` (`stdout=b"".join(kept).decode(errors="replace")`), and
   `docker_cloud.py:312` and `:318` (`stdout=kept.decode(errors="replace")`).
   This is where the cloud corruption happens. The output cap is
   `CAPTURE_LIMIT = 8_000_000` bytes (`sandbox.py:53`), the same as
   `guard.MAX_PATCH_BYTES` (`guard.py:16`), so base64-encoding the diff in the
   sandbox would overflow it. Don't do that.

2. **Produced by a revert.** `coding/runner.py:642`: `diff = await run_git(host, "diff", "--cached", "--binary", ...)`.
   `run_git` (`code/checkouts.py:144`) returns `out.decode(errors="replace")`.

3. **Produced by a local runner.** `apps/cli/src/dotrix_cli/runner.py`: since
   029, `raw_patch = await git_bytes(...)`, then `patch = raw_patch.decode("utf-8")`;
   on `UnicodeDecodeError` the turn is reported `failed` with the reason above.
   The API receives `RunnerResult.patch: str` (`coding/schemas.py`), and
   `coding/local.py:220` stores it:
   `run.pending_patch, run.files_changed, run.summary = patch, files, summary or run.summary`.
   `local.py:279-287` counts its files with `git apply --numstat -z -` fed `input=patch.encode()`.

4. **Stored.** `coding/models.py:146`: `pending_patch: Mapped[str | None] = mapped_column(Text, deferred=True)`;
   `diff` (just below, also `Text`) is what Changes and Files show.
   Written at `runner.py:710` (`run.diff = diff`), `runner.py:1138`
   (`ready_for_acceptance`: `run.pending_patch, run.diff = diff, diff`) and
   `local.py:220`. Cleared to `None` at `service.py:495`, `service.py:596` and
   `runner.py:1170`.

5. **Applied.** `runner.py:1182` (`_stage`):

   ```python
   async def _stage(work: Path, host: Path, diff: str) -> tuple[list[str], list[dict[str, Any]]]:
       patch = work / "changes.patch"
       patch.write_bytes(diff.encode())  # bytes: text mode would add \r before each \n on Windows
       ...
       await run_git(host, "apply", "--index", "--binary", "--whitespace=nowarn", str(patch))
   ```

   Called at `runner.py:545` (cloud) and `runner.py:649` (the publish-only pass,
   with `accepted`, read from `pending_patch` at `runner.py:431`).
   `files.py:166-176` (`_apply`) does the same with `patch.write_bytes(diff.encode())`
   for the Files view, fed from `files.py:94` (`diff` and `pending_patch`).

Good news: application already writes the patch to a file in binary mode and
points `git apply` at the path. Once the value is `bytes`, the
`.encode()` calls go and nothing else in the apply path changes. No sandbox
feeds `git apply` through a text channel.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Services | `pg_isready -h 127.0.0.1` (else `pg_ctlcluster 16 main start`); Redis on 6379 | ready |
| Coding tests | `uv run pytest apps/backend/tests/integration/test_coding.py -q` | all pass |
| Local-turn tests | `uv run pytest apps/backend/tests -q -k "local or runner"` | all pass |
| Sandbox unit tests | `uv run pytest apps/backend/tests/unit -q -k "sandbox or docker_cloud"` | all pass |
| CLI tests | `uv run pytest apps/cli/tests -q` | all pass |
| Migration | `pnpm db:revision "coding patches as bytes"` then `uv run alembic -c apps/backend/alembic.ini check` | "No new upgrade operations detected" |
| Lint | `uv run ruff check apps packages` | All checks passed |
| API client | `pnpm openapi` | `openapi.json` / `schema.ts` regenerated |
| Release check | `python scripts/release.py check` | exit 0 |

Integration tests need `DOTRIX_DATABASE_URL`, `DOTRIX_TEST_DATABASE_URL`,
`DOTRIX_TEST_REDIS_URL` and `DOTRIX_JWT_SECRET` set (see `CLAUDE.md`).

## Scope

**In scope**:

- `apps/backend/src/dotrix_backend/modules/coding/{sandbox,docker_cloud,runner,local,files,models,schemas,service}.py`
- `apps/backend/src/dotrix_backend/modules/code/checkouts.py` (a bytes variant of `run_git`)
- One new Alembic migration in `apps/backend/migrations/versions/`
- `apps/cli/src/dotrix_cli/runner.py`
- Tests: `apps/backend/tests/integration/test_coding.py` and the local-turn tests beside it, `apps/backend/tests/unit/test_docker_cloud.py` / the sandbox unit tests, `apps/cli/tests/test_runner.py`
- `packages/api-client/openapi.json`, `packages/api-client/src/schema.ts` (generated), `CHANGELOG.md`

**Out of scope** (do NOT touch):

- The web's diff and file views (they keep reading `diff` text and the existing endpoints).
- Juno's review and the brief: they read the diff as text for a model, and lossy is fine there.
- Streaming output (`on_line`): it stays decoded text.
- Dropping the old `pending_patch` text column (see Maintenance).

## Git workflow

- Work on the branch the reviewer gives you. Otherwise branch from `stage` and open the PR into `stage`, never `main`.
- One commit per step is fine. Messages: short sentence-case lines.
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: `ExecResult` carries the raw bytes

In `coding/sandbox.py` add a field to `ExecResult`:

```python
    raw: bytes = b""  # stdout exactly as the command wrote it (stdout is decoded with replacements)
```

Set `raw=` alongside `stdout=` at each construction that has the bytes:
`sandbox.py:187`, `sandbox.py:263` (`b"".join(kept)`), and `docker_cloud.py:312`, `:318` (`kept`).
Find any other `ExecResult(` constructions with
`grep -rn "ExecResult(" apps/backend/src` and give each its bytes where it has
them. Constructions in tests keep working through the default.

**Verify**: `grep -rn "ExecResult(" apps/backend/src` — every production
construction that sets `stdout` from bytes also sets `raw`. The sandbox and
Docker Cloud unit tests pass.

### Step 2: A patch is `bytes` from git to storage

- `code/checkouts.py`: split `run_git` as plan 029 did for the CLI: a
  `run_git_bytes(...) -> bytes` with the current body returning `out`, and
  `run_git` returning `(await run_git_bytes(...)).decode(errors="replace")`.
  Its error handling (stderr decoding, `CheckoutError`) stays in the shared part.
- `runner.py:530-545` (cloud): `patch = changes.raw or changes.stdout.encode()`
  (the fallback keeps fake sandboxes in tests working). The size check becomes
  `len(patch) > guard.MAX_PATCH_BYTES`. The emptiness check is `not patch.strip()`.
  Pass `patch` to `_stage`.
- `runner.py:642` (revert): `diff = await run_git_bytes(host, "diff", "--cached", "--binary", "--no-color", "--no-renames")`.
- `_stage(work, host, diff: bytes)` writes `patch.write_bytes(diff)`, dropping the `.encode()`.
- `files.py` `_apply(root, base, diff: bytes)` likewise.

**Verify**: `grep -n "diff.encode()\|patch.encode()" apps/backend/src/dotrix_backend/modules/coding` finds nothing.

### Step 3: Store the bytes

- `models.py`: add `pending_patch_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)` next to `pending_patch`, with a comment saying `pending_patch` (text) is read only for turns that were waiting before this column existed.
- A helper in `models.py` (or `runner.py` if models hold no logic): `def waiting_patch(run) -> bytes | None` returns `run.pending_patch_bytes`, else `run.pending_patch.encode()` if set, else `None`. Where `runner.py:431` and `files.py:94` select the columns directly, select both and apply the same rule.
- Writers set `pending_patch_bytes` and leave `pending_patch` `None`: `runner.py:1138` and `local.py:220`.
- `run.diff` (display) is `patch.decode("utf-8", errors="replace")` wherever it's set from a patch: `runner.py:710`, `runner.py:1138`, `local.py` if it sets it.
- Every place that clears `pending_patch` clears `pending_patch_bytes` too: `service.py:495`, `service.py:596`, `runner.py:1170`. Find any others with `grep -rn "pending_patch" apps/backend/src`.
- Migration: `pnpm db:revision "coding patches as bytes"`. Check the generated file adds one nullable `LargeBinary` column and nothing else, with a matching `downgrade`. No data copy: `waiting_patch` reads old rows.

**Verify**: `uv run alembic -c apps/backend/alembic.ini check` reports no new operations; `uv run pytest apps/backend/tests/integration/test_coding.py -q` passes.

### Step 4: Local runners send bytes

- `coding/schemas.py` `RunnerResult`: add `patch_b64: str | None = None`. In `local.py`, the patch is `base64.b64decode(result.patch_b64, validate=True)` when it's set (a bad value is a 422 with a clear message), else `result.patch.encode()` as today. The size check and the `numstat` at `local.py:279-287` take the bytes (`input=patch`).
- `apps/cli/src/dotrix_cli/runner.py`: always send `patch_b64=base64.b64encode(raw_patch).decode()`. Also send `patch` when `raw_patch` decodes as UTF-8, so a new runner still works against a platform without this plan (it ignores unknown fields and would otherwise see no changes). Remove plan 029's `UnicodeDecodeError` refusal and its reason text. Leave 029's step flush and 2,000-step cap exactly as they are.
- `pnpm openapi`, and commit the regenerated `openapi.json` and `schema.ts`.

**Verify**: `grep -n "isn't UTF-8 text" apps/cli/src/dotrix_cli/runner.py` finds nothing; `git diff --stat packages/api-client` shows the two generated files.

### Step 5: Tests

Use the fixtures and fakes the existing tests use (the scripted engine and fake sandbox in `test_coding.py`, the inline `Api` stub in `apps/cli/tests/test_runner.py`). Each must fail on the code before this plan. Run it against the old code once and say so in your report.

1. **Cloud, Latin-1 change.** A fake sandbox whose diff `raw` holds a patch adding `b"caf\xe9\n"` to a file. After the turn, the file in the host checkout's index (`git show :path`, read as bytes) is exactly `b"caf\xe9\n"`, and `run.diff` contains `caf�` (display only).
2. **Manual accept, Latin-1.** The same change in Manual waits as `changes_ready`; accepting it runs the publish-only pass, and the applied bytes are exact.
3. **Waiting from before the migration.** A run with `pending_patch` (text) set and `pending_patch_bytes` `None` still publishes.
4. **Local result with `patch_b64`.** A Latin-1 patch sent as `patch_b64` is stored as `pending_patch_bytes`, byte for byte, and its `files_changed` counts are right. An invalid `patch_b64` gets a 422.
5. **Revert of a Latin-1 turn** restores the original bytes.
6. **CLI.** A Latin-1 change is sent as `patch_b64` decoding to the exact bytes, with no `patch` field; a UTF-8 change sends both. The turn's outcome is `changes`, not `failed`.

**Verify**: the commands from the table all pass.

### Step 6: Changelog

Under `## [Unreleased]` → the existing `### Fixed` (don't add a second heading):

`- Kai's changes to files that aren't UTF-8 text (older encodings such as Latin-1) are now pushed exactly as written, from cloud and local turns; before, cloud turns replaced those characters and local turns refused them.`

**Verify**: `python scripts/release.py check` exits 0 and `pnpm format:check` exits 0.

## Done criteria

- [ ] All six tests in Step 5 exist, failed on the old code, and pass
- [ ] `uv run pytest apps/backend/tests/integration/test_coding.py apps/cli/tests -q` and the sandbox unit tests pass
- [ ] `uv run alembic -c apps/backend/alembic.ini check` clean; the migration adds one nullable column only
- [ ] `grep -rn "diff.encode()\|patch.encode()" apps/backend/src/dotrix_backend/modules/coding` finds nothing, except the `waiting_patch` fallback for old rows
- [ ] `grep -n "isn't UTF-8 text" apps/cli/src/dotrix_cli/runner.py` finds nothing
- [ ] `uv run ruff check apps packages` clean; `pnpm openapi` leaves no uncommitted diff; `python scripts/release.py check` exit 0
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

- An `ExecResult` construction in production code has only decoded text, not the bytes (say which, with the line).
- Something other than display or a model prompt needs the patch as `str` (name the line).
- The generated migration does more than add the one column, or `alembic check` still reports differences after it.
- Any sandbox implementation feeds `git apply` through stdin as text rather than through the written file.

## Maintenance notes

- `diff` is lossy display text. Anything that writes files must use the bytes (`waiting_patch`, or the value from `run_git_bytes`/`ExecResult.raw`). A reviewer should reject a new `.encode()` on a diff.
- The `pending_patch` text column can be dropped in a later release once no row has it set (`select count(*) from coding_runs where pending_patch is not null` returns 0); turns in `changes_ready` are short-lived.
- `run_git` stays lossy for everything that's not a patch (names, numstat, messages). Use `run_git_bytes` only where bytes are written back.
- Older CLI runners keep sending `patch` (text): those turns behave as before this plan. The desktop app's bundled CLI picks up the change in its next release.
