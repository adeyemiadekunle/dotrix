# Plan 044: dotrix chat lists the conversation's saved plans and builds the version you pick

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat ee73ad4..HEAD -- apps/cli/src/dotrix_cli/cli.py apps/cli/src/dotrix_cli/agent_client.py`
> If any of these changed, compare the "Current state" excerpts against the
> live code; on a mismatch in the lines this plan changes, treat it as a STOP
> condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: feature
- **Planned at**: commit `ee73ad4`, 2026-11-12

## Why this matters

In Chat's Plan mode, Nova saves versions of the conversation's plan, and the web shows each as a card
with "Build this plan". A Build message can name the exact version (`plan_id`); without one, the platform
pins the latest. `dotrix chat --mode plan` already works, but there's no way to see the saved versions
or pick one, so a terminal user can only ever build the latest.

## Current state

- `apps/cli/src/dotrix_cli/cli.py` `_ChatSession` (line ~1094) handles slash commands (`/mode`, `/approvals`, `/continue` …) in a
  method around line 1120, and sends messages through `PlatformAgent` (`apps/cli/src/dotrix_cli/agent_client.py`), whose send
  (line ~80) builds the body with `work_mode` when set.
- API: `GET /v1/workspaces/{ws}/projects/{p}/agent/threads/{thread_id}/plans` returns
  `list[PlanRead]` (`apps/backend/src/dotrix_backend/modules/agents/schemas.py:444`): `id`, `thread_id`,
  `version`, `run_id`, `title`, `summary`, `acceptance_criteria`, `tasks`. Confirm the exact path in
  `agents/router.py:214` (`list_thread_plans`) and its router prefix.
- The run-create body accepts `plan_id: uuid | None` ("Exact private plan version to build in this
  conversation"; `agents/schemas.py:58`), used with `work_mode: build`.
- Tests: `apps/cli/tests/test_chat_modes.py` drives `_ChatSession` against `FakePlatform`.

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

- `apps/cli/src/dotrix_cli/cli.py` (`_ChatSession`)
- `apps/cli/src/dotrix_cli/agent_client.py` (send with `plan_id`; a `plans(thread_id)` call)
- `apps/cli/tests/test_chat_modes.py`, `fake_platform.py` (a canned plans response)
- `CHANGELOG.md` (one line under Unreleased, in the existing section of its kind; never add a second heading)

**Out of scope** (do NOT touch):

- The backend.
- Cross-project conversations (they have no work modes).

## Git workflow

- Work on the branch the reviewer gives you. Otherwise branch from `stage` and open the PR into `stage`, never `main`.
- Commit messages: one short sentence-case line.
- Do NOT push or open a PR unless instructed. Never use bare `git stash`.

## Steps

### Step 1: `/plans`

In a chat session with a thread, `/plans` lists the conversation's saved plans, newest first: `v3  <title>`
with its task count and saved time, and marks the newest. With no thread yet, or no plans, say so.

### Step 2: `/build [VERSION]`

`/build` switches to Build mode and sends "Build this plan" with the chosen version's `plan_id`
(default: the newest). `/build 2` picks version 2; an unknown version is refused locally with the list
of versions. It goes through the same send path as a typed Build message, so approvals and Kai's
session announcement work as they do now.

### Step 3: Help and changelog

Add both to the session's slash-command help and to `dotrix chat --help`. Under Unreleased → Added:
`- dotrix chat: /plans lists the conversation's saved plans, and /build [version] builds the one you pick.`

## Test plan

In `test_chat_modes.py`:

1. `/plans` with two saved versions prints both, newest first, and marks the newest.
2. `/build` sends `work_mode: build` and the newest plan's `id` as `plan_id`.
3. `/build 1` sends version 1's id.
4. `/build 9` is refused without a request and lists the versions.
5. `/plans` before the conversation has a thread says there's nothing yet, without a request.
6. A message typed in Build mode without `/build` sends no `plan_id` (today's behaviour).

Every new test must fail on the code before your change. Check that (a temporary WIP commit, then the old source checked out) and say how in your report.

## Done criteria

- [ ] The six tests pass and fail before the change
- [ ] `uv run pytest apps/cli/tests -q` passes
- [ ] ruff clean; release check exit 0
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` status row updated (unless the reviewer maintains it)

## STOP conditions

- The plans route or `plan_id` differ from "Current state".
- The session has no stable thread id to list plans for (name where it comes from).

## Maintenance notes

- If the platform later adds plans to cross-project conversations, `/plans` can follow.
