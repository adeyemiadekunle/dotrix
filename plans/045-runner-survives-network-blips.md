# Plan 045: dotrix runner keeps running through a brief network or server outage

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat ee73ad4..HEAD -- apps/cli/src/dotrix_cli/runner.py apps/cli/src/dotrix_cli/cli.py`
> If any of these changed, compare the "Current state" excerpts against the
> live code; on a mismatch in the lines this plan changes, treat it as a STOP
> condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `ee73ad4`, 2026-11-12

## Why this matters

`dotrix runner` (and the desktop app, which runs it in the background) waits for local coding turns
by polling the platform. When a poll fails because the network dropped, the laptop slept, or the
server was redeploying, the error escapes the loop and **the runner exits**. Turns approved after that
sit waiting for a computer that isn't listening, until someone restarts it. The desktop app restarts a
crashed runner, but the CLI doesn't, and nothing tells the person why their turn never started.

A single turn already copes: heartbeats that fail are retried (plan 029). It's the waiting loop that doesn't.

## Current state

`apps/cli/src/dotrix_cli/runner.py`:

```python
    async def serve(self, *, poll_seconds: float = 5, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        await self.clean_worktrees()
        while not stop.is_set():
            try:
                if await self.once():
                    continue
            except LeaseLost:
                continue
            try:
                await asyncio.wait_for(stop.wait(), poll_seconds)
            except TimeoutError:
                pass
```

- `once()` (line ~358) calls `register()` the first time, then `self.api.post(f"{self.base}/{self.runner_id}/claim")`;
  any exception from those leaves `serve`.
- `apps/cli/src/dotrix_cli/platform.py` turns a transport failure into `PlatformError(0, "unreachable", "Can't reach …")`, and
  an HTTP error into `PlatformError(status, <problem type>, detail)`.
- `apps/cli/src/dotrix_cli/cli.py` `runner_command` (line ~590) runs `asyncio.run(runner.serve(poll_seconds=poll))` and turns a
  `PlatformError` into `_fail(...)`: the process exits.
- Tests: `apps/cli/tests/test_runner.py` drives `LocalRunner` with an inline `Api` stub whose `post` can
  raise on chosen calls.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| CLI tests | `uv run pytest apps/cli/tests -q` | pass |
| Lint | `uv run ruff check apps packages` | All checks passed |
| Release check | `python scripts/release.py check` | exit 0 |
| Format | `pnpm format:check` | exit 0 |

Integration tests need Postgres and Redis (`pnpm db:up`) and the `DOTRIX_*` test variables described in `CLAUDE.md`.

## Scope

**In scope**:

- `apps/cli/src/dotrix_cli/runner.py` (`serve`, and a small helper deciding what's worth retrying)
- `apps/cli/src/dotrix_cli/cli.py` (`runner_command`, only if a message changes)
- `apps/cli/tests/test_runner.py`
- the desktop app only if its status parsing needs a new `--json` event (check `apps/desktop/src/runner.ts`)
- `CHANGELOG.md` (one line under Unreleased, in the existing section of its kind; never add a second heading)

**Out of scope** (do NOT touch):

- Retries inside a turn (`work`, heartbeats, the result): plan 029 covers them.
- Authentication: a revoked token or a removed runner must still stop it.

## Git workflow

- Work on the branch the reviewer gives you. Otherwise branch from `stage` and open the PR into `stage`, never `main`.
- Commit messages: one short sentence-case line.
- Do NOT push or open a PR unless instructed. Never use bare `git stash`.

## Steps

### Step 1: What's worth waiting out

Add `_transient(exc) -> bool`: true for `PlatformError` with `status == 0` (unreachable), `status >= 500`,
or `status == 429`; false for everything else. A 401 or 403 (signed out, token revoked), a 404 (runner
removed), and `LeaseLost` keep their current handling.

### Step 2: Wait it out in `serve`

Around `once()` in `serve`, catch a transient error: say so once ("Can't reach dotrix; trying again…")
through the runner's existing output (`self.notify` for `--json`, plain text otherwise, as the class does
now), then wait with backoff: 5 s doubling to at most 60 s, honouring `stop` so Ctrl-C and the desktop app's
stop still end it at once. On the first success after an outage, say "Connected again". Reset the backoff
then. Non-transient errors still leave `serve` as today.

If `register()` fails transiently on the first call, the same applies: it's retried on the next pass.

### Step 3: `--json` for the desktop app

If the runner emits `--json` events, add `{"event": "offline", "retry_in": N}` and `{"event": "online"}`.
Check `apps/desktop/src/runner.ts` ignores unknown events (it should); if it would treat them as errors, STOP.

### Step 4: Changelog

Under Unreleased → Fixed: `- dotrix runner (and the desktop app's local coding) keeps waiting through a brief network or server outage instead of exiting.`

## Test plan

In `test_runner.py`, with the inline `Api` stub and a short poll interval (patch the backoff to milliseconds):

1. `claim` raises `PlatformError(0, "unreachable", …)` twice, then returns a turn: `serve` codes the turn and doesn't exit.
2. A 503 and a 429 are retried the same way.
3. A 401 from `claim` ends `serve` with that error (today's behaviour).
4. `stop` set during the backoff ends `serve` within one poll interval.
5. The "trying again" message appears once per outage, and "Connected again" once after it.
6. With `--json`, the `offline` and `online` events are emitted.

Every new test must fail on the code before your change. Check that (a temporary WIP commit, then the old source checked out) and say how in your report.

## Done criteria

- [ ] The six tests pass; tests 1, 2 and 6 fail before the change
- [ ] `uv run pytest apps/cli/tests -q` passes
- [ ] ruff clean; release check exit 0
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` status row updated (unless the reviewer maintains it)

## STOP conditions

- The desktop app treats an unknown `--json` event as a failure.
- `PlatformError` doesn't carry the status this plan relies on.

## Maintenance notes

- Keep the backoff cap low (60 s): a runner offline for a while should pick work up within a minute of the network returning.
- If the platform ever answers 503 on purpose for maintenance, this behaviour is what we want.
