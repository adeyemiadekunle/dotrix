# Plan 019: Two requests can't start coding on the same issue or session at once

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/backend/src/dotrix_backend/modules/coding/service.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

Starting a coding turn checks that the issue (or the session) has no turn waiting or working, then creates one. The check and the insert are not serialised: two requests that arrive together — a double click, two tabs, a start from Codes racing one triggered by assigning Kai — both pass the check. The result is two active turns on one issue, or two turns with the same number on one session's branch; in Accept edits or Auto both start at once and can push to the same branch. After this plan the starts are serialised per project, so the second request gets the existing "already has a coding run" conflict.

## Current state

`apps/backend/src/dotrix_backend/modules/coding/service.py` (`CodingService`):

- `_codable(...)` is the gate every start goes through. Its busy check (around lines 397-401):

```python
        busy = await self.session.scalar(
            select(CodingRun.id).where(CodingRun.issue_id == issue.id, CodingRun.status.in_(ACTIVE))
        )
        if busy is not None and not busy_ok:
            raise CodingBusy(f"{issue.key} already has a coding run waiting or working")
        return issue
```

- `start(...)` (around line 248) locks the project row only when the request comes from a conversation:

```python
        if thread_id:
            await self.session.scalar(select(Project).where(Project.workspace_id == access.member.workspace_id,
                                                           Project.id == access.project.id).with_for_update())
            busy = await self.session.scalar(select(CodingRun.id).where(
                CodingRun.workspace_id == access.member.workspace_id, CodingRun.thread_id == thread_id,
                CodingRun.status.in_(ACTIVE)).limit(1))
            if busy:
                raise CodingBusy("Kai already has an active turn in this conversation")
        issue = await self._codable(access.project, access.member.user_id, key, location=data.location)
```

- `_next_turn(...)` (around line 342) reads the session's turns without a lock and the caller numbers the new turn `turns[-1].turn + 1`:

```python
        turns = await self._turns(access, session_id)
        if turns[0].requested_by_id != access.member.user_id:
            raise Forbidden("Only whoever started this session can continue it")
        if any(t.status in ACTIVE for t in turns):
            raise CodingBusy("This session has a turn waiting or working; follow up once it's done")
```

- `_turns` already reads with `.execution_options(populate_existing=True)`.
- `ACTIVE` is defined in `modules/coding/models.py` (line 94). There is no unique constraint on active runs per issue or on `(session_id, turn)`.

The locking helper to use: `ProjectRepository(self.session).get(workspace_id, project_id, for_update=True)` (`modules/projects/repository.py`; `modules/issues/service.py:237` uses it the same way). A row lock is held until the transaction commits or rolls back, which is exactly the span of check-then-insert here.

Existing tests: `apps/backend/tests/integration/test_coding.py` (fixtures set up a fake GitHub, a sandbox and a `coding` worker; search it for `already has a coding run` to find the existing busy test and its setup).

Repo conventions that apply (from the repository's `CLAUDE.md`): backend layering is router → service, routers never query; raise domain exceptions from `dotrix_backend.core.errors`; every query is scoped by workspace or project; services commit once per unit of work; line length 100; every PR adds a line under `## [Unreleased]` in `CHANGELOG.md`, written for people who use dotrix, in the existing section of the right kind.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync` | exit 0 |
| Local services (integration tests need Postgres and Redis) | `pnpm db:up` | containers running |
| Python lint | `uv run ruff check apps packages` | exit 0 |
| Release check | `python scripts/release.py check` | exit 0 |
| Coding tests | `uv run pytest apps/backend/tests/integration/test_coding.py -q` | all pass |

## Scope

**In scope** (the only files you should modify):

- `apps/backend/src/dotrix_backend/modules/coding/service.py`
- `apps/backend/tests/integration/test_coding.py` (add tests)
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- A database constraint (a partial unique index on active runs, or unique `(session_id, turn)`): existing rows and the publish-only pass make that a separate, riskier change; see Maintenance.
- `modules/coding/local.py`, `runner.py`, `recovery.py`.
- The conversation-scoped check in `start`: keep it.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/019-one-coding-turn-at-a-time-per-issue origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Write the failing test

In `tests/integration/test_coding.py`, next to the existing busy test, add `test_two_starts_at_once_give_one_turn`: set up an issue exactly as that test does, then fire two `POST {base}/coding/issues/{key}/runs` requests together with `asyncio.gather` and assert that exactly one answers 201/200 and the other 409, and that the database holds exactly one `CodingRun` for the issue with a status in `ACTIVE`.

Read `tests/conftest.py` first: integration tests run inside one rolled-back transaction per test, on one connection. If both requests share that connection they cannot race, and the test would pass before the fix. In that case write the test at the service level instead: open two independent sessions from the app's session factory (`db_client._transport.app.state.sessionmaker`), build a `CodingService` on each the way the router's dependency does (read `modules/coding/router.py` for its constructor arguments), call `start` on both with `asyncio.gather(..., return_exceptions=True)`, and assert one result is a `CodingBusy`. Clean up the rows you committed at the end of the test.

**Verify**: the new test FAILS before the code change (two active runs). If you cannot make it fail before the change by either route, STOP and report: do not ship a test that can't detect the bug.

### Step 2: Serialise in `_codable`

In `_codable`, before the `busy` query, lock the project row:

```python
        # One start at a time per project: the busy check below and the insert that follows it
        # can't interleave with another request's.
        await ProjectRepository(self.session).get(project.workspace_id, project.id, for_update=True)
```

Import `ProjectRepository` if the file doesn't already. Place it after the availability checks (which may raise without needing the lock) and before `IssueService(self.session).get(...)`.

### Step 3: Serialise follow-ups

In `_next_turn`, take the same lock as the first statement, before `self._turns(...)`, so the turns read after it are current (`_turns` already repopulates). Do the same at the top of any other method that computes `turns[-1].turn + 1` (`grep -n "turn + 1\|\.turn + 1" apps/backend/src/dotrix_backend/modules/coding/service.py`).

**Verify**: `uv run pytest apps/backend/tests/integration/test_coding.py -q` → all pass, including the new test

### Step 4: A second test, lint, changelog

Add `test_two_follow_ups_at_once_give_one_turn` in the same style for a session with a finished first turn: one follow-up is created, the other gets 409, and no two turns of the session share a number.

CHANGELOG → Unreleased → Fixed: `- Asking Kai to start on the same task twice at the same moment (a double click, two tabs) now gives one coding turn, not two.`

**Verify**: `uv run ruff check apps packages` → exit 0; `python scripts/release.py check` → exit 0

## Test plan

- Two new tests in `tests/integration/test_coding.py` (Steps 1 and 4), modelled on the existing busy test there.

## Done criteria

- [ ] `uv run pytest apps/backend/tests/integration/test_coding.py -q` exits 0 with both new tests present and not skipped
- [ ] `uv run ruff check apps packages` exits 0
- [ ] `grep -n "for_update=True" apps/backend/src/dotrix_backend/modules/coding/service.py` shows the new locks in `_codable` and `_next_turn`
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- Neither test route in Step 1 can reproduce the race.
- Taking the project lock in `_codable` deadlocks or times out an existing test (two code paths locking in different orders): report the two paths.

## Maintenance notes

- The lock is per project, so two people starting turns on different issues of one project queue briefly behind each other; the critical section is a few queries.
- Follow-up worth considering: a partial unique index on `(issue_id) WHERE status IN (active statuses)` and a unique `(session_id, turn)` as a database backstop. Check existing data and the publish-only pass (which re-queues the same row) before adding either.
- A reviewer should confirm every path that creates a `CodingRun` goes through `_codable` or `_next_turn` (`grep -n "self._create(" modules/coding/service.py`).
