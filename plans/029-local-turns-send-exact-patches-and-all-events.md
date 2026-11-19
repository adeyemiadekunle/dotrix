# Plan 029: A turn coded on your computer sends its patch byte for byte and all of its steps

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/cli/src/dotrix_cli/runner.py apps/backend/src/dotrix_backend/modules/coding/schemas.py apps/backend/src/dotrix_backend/modules/coding/local.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (wire format between the CLI and the API)
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

When Kai codes a turn on a person's own computer, the runner sends the changes back as a patch. It reads git's output as UTF-8 and replaces anything that isn't: a file in Latin-1 or Shift-JIS, or a file name that isn't UTF-8, comes back with replacement characters. The platform then either can't apply the patch or writes the damaged text into the repository. Separately, the runner sends at most 50 steps with the final result and never sends the rest, so after a burst of output, or after a few failed heartbeats, the last steps of a turn — the ones that explain a failure — are missing from the session. After this plan the patch travels as exact bytes and every step is delivered before the result.

## Current state

`apps/cli/src/dotrix_cli/runner.py`:

```python
EVENTS_PER_BEAT = 50
...
async def git(cwd: Path, *args: str, check: bool = True) -> str:
    ...
    out, err = await process.communicate()
    if check and process.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: {err.decode(errors='replace').strip()[:500]}")
    return out.decode(errors="replace")
```

Inside the turn (around lines 420-436):

```python
        async def beat(extra: dict[str, Any] | None = None) -> bool:
            body = {"lease_token": token, "events": pending[:EVENTS_PER_BEAT], **(extra or {})}
            try:
                answer = await self.api.post(f"{path}/heartbeat", body)
            except Exception as exc:
                if _lost(exc):
                    raise LeaseLost() from exc
                return False  # the platform may be back before the lease runs out
            del pending[:EVENTS_PER_BEAT]
            return bool(answer.get("stop"))

        async def report(outcome: str, **fields: Any) -> None:
            try:
                await self.api.post(f"{path}/result", {"lease_token": token, "outcome": outcome,
                                                       "events": pending[:EVENTS_PER_BEAT], **fields})
```

and at the end (around lines 544-560):

```python
        await git(tree, "add", "-A")
        patch = await git(tree, "diff", "--cached", "--binary", "--no-color", "--no-ext-diff", "--no-textconv",
                          "--no-renames", base_sha)
        ...
        if not patch.strip():
            ...
        await report("changes", base_sha=base_sha, patch=patch, summary=out.summary or _tail(stderr), **usage)
```

The API side, `apps/backend/src/dotrix_backend/modules/coding/schemas.py`:

```python
class RunnerHeartbeat(BaseModel):
    lease_token: int
    events: list[RunnerEvent] = Field(default_factory=list, max_length=200)
    ...
class RunnerResult(BaseModel):
    ...
    patch: str | None = Field(default=None, max_length=20_000_000, description="`git diff --cached --binary` against base_sha")
    ...
    events: list[RunnerEvent] = Field(default_factory=list, max_length=200)
```

and `modules/coding/local.py` (around lines 200-217): `patch = data.patch or ""`, a size check `len(patch.encode()) > guard.MAX_PATCH_BYTES`, `patch_files(patch)` (which runs `git apply --numstat -z -` with `input=patch.encode()`), then `ready_for_acceptance(self.session, run, patch, files, summary, …)`, which stores the patch (`coding_runs.pending_patch`, a text column) for the publish pass; the worker later writes it with `patch.write_bytes(diff.encode())` (`modules/coding/runner.py:1185`).

Old runners stay in use (the desktop app bundles a CLI and updates on its own schedule), so the API must keep accepting the current `patch` string.

Tests: `apps/cli/tests/test_runner.py` (a fake platform in `apps/cli/tests/fake_platform.py`) and the local-turn tests in `apps/backend/tests/integration/test_coding.py` (`_local_runner(...)`, `test_a_local_turn_…`).

Repo conventions that apply (from the repository's `CLAUDE.md`): backend layering is router → service, routers never query; raise domain exceptions from `dotrix_backend.core.errors`; every query is scoped by workspace or project; services commit once per unit of work; line length 100; every PR adds a line under `## [Unreleased]` in `CHANGELOG.md`, written for people who use dotrix, in the existing section of the right kind.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync` | exit 0 |
| Local services (integration tests need Postgres and Redis) | `pnpm db:up` | containers running |
| Python lint | `uv run ruff check apps packages` | exit 0 |
| Release check | `python scripts/release.py check` | exit 0 |
| CLI tests | `uv run pytest apps/cli/tests -q` | all pass |
| Coding tests | `uv run pytest apps/backend/tests/integration/test_coding.py -q` | all pass |
| Regenerate API schema + client | `pnpm openapi` | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `apps/cli/src/dotrix_cli/runner.py`, `apps/cli/tests/test_runner.py`, `apps/cli/tests/fake_platform.py`
- `apps/backend/src/dotrix_backend/modules/coding/schemas.py`, `local.py`
- `apps/backend/tests/integration/test_coding.py` (add tests)
- `packages/api-client/openapi.json`, `packages/api-client/src/schema.ts` (via `pnpm openapi` only)
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- How the pending patch is stored (`coding_runs.pending_patch` stays a text column; see Step 2 for how bytes fit in it) — no migration.
- The cloud worker's own patch path.
- The runner dying on a network error, and killing the tool's process group on Stop: separate findings.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/029-local-turns-send-exact-patches-and-all-events origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Bytes from git

Add `async def git_bytes(cwd, *args, check=True) -> bytes` beside `git` (same process handling, returns `out` undecoded) and use it for the `diff --cached --binary` call. `git` itself stays for every other use. `if not patch.strip()` works on bytes.

### Step 2: Send the patch as base64, accept both

`RunnerResult` gains `patch_b64: str | None = Field(default=None, max_length=28_000_000, description="The patch's exact bytes, base64")`. In `local.py`, when `patch_b64` is present decode it (`base64.b64decode(..., validate=True)`; a decode error fails the turn with the existing "weren't a patch git can read" outcome) and use those bytes; otherwise use `data.patch.encode()` as today. From there on, work in bytes for the size check and `patch_files`.

Storing it: `pending_patch` is text. Read every reader of `pending_patch` and of the `patch` argument of `ready_for_acceptance` (`grep -rn "pending_patch" apps/backend/src`). Use the reversible mapping `raw.decode("utf-8", "surrogateescape")` when storing and `text.encode("utf-8", "surrogateescape")` at each reader, in one pair of helper functions in `modules/coding/guard.py` or `local.py` (say where), so valid UTF-8 patches are stored exactly as today and other bytes survive. Before relying on it, confirm with a two-line test against the test database that Postgres accepts such a string in a text column; if it rejects lone surrogates, STOP and report (the alternative is a schema change, which is out of scope).

The runner sends `patch_b64` only. An old API ignores unknown fields? It doesn't matter in that direction: the runner and the API are released together and the API is the side that must stay compatible; but check `RunnerResult`'s model config — if it forbids extra fields, an old API would reject a new runner, so note in your report which it is.

### Step 3: Deliver every event

- Raise `EVENTS_PER_BEAT` to the API's limit only if you also keep it at or below `max_length=200`; simplest is to leave it at 50.
- Before `report(...)`, flush: `while len(pending) > EVENTS_PER_BEAT: await beat()` with a bound on attempts (if a heartbeat fails three times in a row, stop flushing and go on to the result).
- `report` sends `pending[:EVENTS_PER_BEAT]` and, on success, clears them. If events remain that could not be delivered, append one final event saying so (`"N earlier steps couldn't be sent"`), using the same event shape the runner already produces for a step.
- Cap `pending` at 2,000 entries while heartbeats are failing: drop the oldest and count them for that same message.

### Step 4: Tests

`apps/cli/tests/test_runner.py` (the fake platform records what it receives; extend `fake_platform.py` to keep the raw result body and to fail a chosen number of heartbeats):

1. A repository with a Latin-1 text file (`"caf\xe9\n".encode("latin-1")` committed, then changed by the fake tool): the bytes decoded from the result's `patch_b64` apply cleanly with `git apply --index --binary` to a fresh checkout at `base_sha`, and the file's bytes equal what the tool wrote. This test must fail before Step 1 (the old path sends U+FFFD).
2. A tool that emits 180 steps in one burst: the platform receives all 180, in order, across heartbeats and the result.
3. Three failed heartbeats then recovery: no step is lost.
4. Heartbeats failing throughout: the result is still sent, with a final "couldn't be sent" event.

`tests/integration/test_coding.py`: a local turn reported with `patch_b64` of a patch containing non-UTF-8 bytes ends `changes_ready` with the right changed files, and accepting it pushes a commit whose file bytes match; a result with the old `patch` field still works (the existing tests cover it: keep them unchanged).

**Verify**: `uv run pytest apps/cli/tests -q` and `uv run pytest apps/backend/tests/integration/test_coding.py -q` → all pass

### Step 5: Schema, lint, changelog

`pnpm openapi`; `uv run ruff check apps packages`. CHANGELOG → Unreleased → Fixed: `- A turn coded on your computer now sends files that aren't UTF-8 exactly as they are, and every step of the turn reaches the session, including the last ones.`

**Verify**: `uv run python apps/backend/scripts/export_openapi.py && git diff --exit-code packages/api-client/openapi.json` → exit 0; `python scripts/release.py check` → exit 0

## Test plan

- Four runner tests and two integration tests (Step 4), modelled on the existing ones in the same files.

## Done criteria

- [ ] `uv run pytest apps/cli/tests -q` and `uv run pytest apps/backend/tests/integration/test_coding.py -q` exit 0
- [ ] `grep -n 'errors="replace"' apps/cli/src/dotrix_cli/runner.py` shows no use on the patch path
- [ ] The OpenAPI schema is current; `uv run ruff check apps packages` exits 0
- [ ] The existing local-turn tests pass unchanged (old `patch` field still accepted)
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- Postgres rejects a surrogate-escaped string in `pending_patch` (Step 2).
- A reader of `pending_patch` hands it to something that needs real text (for example it is shown in the UI as a diff): report the reader; the diff shown to people may need its own lossy rendering.
- `apps/cli/tests/fake_platform.py` can't be extended to fail heartbeats without rewriting it.

## Maintenance notes

- The old `patch` string field can be removed once no supported desktop or CLI release sends it; leave a dated comment on the field.
- Related, not fixed here: `dotrix runner` exits on a transient network error instead of retrying, and Stop can leave the tool's child processes running.
- A reviewer should check the size limit still applies to the decoded bytes.
