# Plan 042: The CLI asks Kai for a Plan turn, and builds from a plan you choose

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat ee73ad4..HEAD -- apps/cli/src/dotrix_cli/cli.py apps/cli/src/dotrix_cli/codes.py`
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

Codes has two kinds of turn since #254: a **Plan** turn, where Kai reads the repository and returns a
plan without changing anything, and a **Build** turn. A Build turn can name the Plan turn it builds
from. The web app offers both. The CLI can only start Build turns, so someone working from a terminal
can't ask for a plan first or say which plan to build.

## Current state

- `apps/cli/src/dotrix_cli/cli.py` `code_command` (line ~600) posts `{"note", "location", "approval_mode"?, "model"?}` to
  `.../coding/issues/{KEY}/runs`; it never sends `work_mode`.
- `apps/cli/src/dotrix_cli/codes.py` `Codes.follow_up` (line ~137) posts `{"message", "approval_mode"?}` to
  `.../coding/sessions/{session_id}/turns`, and `dotrix codes follow` calls it.
- The API (`apps/backend/src/dotrix_backend/modules/coding/schemas.py`):
  - `CodingRunCreate.work_mode: Literal["plan", "build"] = "build"`
  - `CodingFollowUp.work_mode` and `source_plan_id: uuid | None`. `source_plan_id` is the **id of a
    completed Plan turn in the same session** (the service looks for that turn with a `plan_result`
    and refuses anything else with 422 "Select a completed plan from this coding session to build"),
    and is only valid with `work_mode: build`.
  - A Plan turn must run in the cloud: `location: local` with `work_mode: plan` is refused with 422
    ("Plan mode requires a platform sandbox with read-only enforcement"; `coding/service.py:278` and `:323`).
- `CodingRunRead` returns `work_mode` and `plan_result` (`title`, `summary`, `acceptance_criteria`,
  `tasks` of `{title, detail, depends_on}`, `open_questions`, optional `execution`).
- Tests: `apps/cli/tests/test_codes.py` with `FakePlatform` (`fake_platform.py`), whose `bodies(suffix)`
  returns the JSON bodies sent to a path.

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

- `apps/cli/src/dotrix_cli/cli.py` (`code_command`)
- `apps/cli/src/dotrix_cli/codes.py` (`follow_up`, the `follow` command)
- `apps/cli/tests/test_codes.py` (and `fake_platform.py` only if a canned response needs a `work_mode`)
- `CHANGELOG.md` (one line under Unreleased, in the existing section of its kind; never add a second heading)

**Out of scope** (do NOT touch):

- The backend and the API.
- `codes show` (plan 043 prints plans and tasks).
- `dotrix chat` (plan 044).

## Git workflow

- Work on the branch the reviewer gives you. Otherwise branch from `stage` and open the PR into `stage`, never `main`.
- Commit messages: one short sentence-case line.
- Do NOT push or open a PR unless instructed. Never use bare `git stash`.

## Steps

### Step 1: `dotrix code KEY --plan-only`

Add `--plan-only` to `code_command`: sends `"work_mode": "plan"`. Because a Plan turn must run in the cloud,
`--plan-only` without `--cloud` exits with a clear message before calling the API ("A Plan turn runs in the
platform's sandbox: add --cloud"). Don't silently switch to the cloud. The printed line says "Kai's Plan turn".

(Name it `--plan-only`, not `--plan`, because Step 2 uses `--plan` for choosing a plan to build.)

### Step 2: `dotrix codes follow TARGET MESSAGE` gains `--plan-only` and `--plan TURN`

- `--plan-only` sends `"work_mode": "plan"`. When the session's turns are local, also send
  `"location": "cloud"`, since the API refuses a local Plan turn. Say so in the output.
- `--plan TURN` builds from a Plan turn of this session: TURN is the turn's number as `codes show` prints it
  (`Turn 3`), or the start of its run id. Resolve it from `Codes.turns(session_id)`. Refuse locally, before
  the API, when that turn isn't a Plan turn or has no `plan_result` ("Turn 3 isn't a finished plan"). Send
  `"work_mode": "build", "source_plan_id": <its run id>`.
- `--plan-only` and `--plan` together is an error.
- Pass `work_mode` and `source_plan_id` through `Codes.follow_up`, keeping its current behaviour when neither is set.

### Step 3: Help and changelog

Update both commands' help to say what a Plan turn is. Add one line under Unreleased → Added in
`CHANGELOG.md`: `- dotrix code --plan-only and dotrix codes follow --plan-only ask Kai for a plan first; --plan TURN builds from that plan.`

## Test plan

In `apps/cli/tests/test_codes.py`, with `FakePlatform`:

1. `code KUN-7 --plan-only --cloud` sends `work_mode: plan` and `location: cloud`; the output names a Plan turn.
2. `code KUN-7 --plan-only` without `--cloud` exits non-zero with the message and sends no request.
3. `codes follow kun-7 "next" --plan-only` sends `work_mode: plan`; on a local session it also sends `location: cloud`.
4. `codes follow kun-7 "build it" --plan 2` where turn 2 is a Plan turn with a `plan_result` sends `work_mode: build` and that turn's id as `source_plan_id`.
5. `--plan 1` where turn 1 is a Build turn exits non-zero without a request.
6. `--plan-only --plan 2` is refused.
7. A plain `codes follow` and `code` send exactly what they send today (no `work_mode` key, or `build`): existing tests stay green.

Every new test must fail on the code before your change. Check that (a temporary WIP commit, then the old source checked out) and say how in your report.

## Done criteria

- [ ] The seven tests pass and the new ones fail before the change
- [ ] `uv run pytest apps/cli/tests -q` passes
- [ ] ruff clean; `python scripts/release.py check` exit 0
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` status row updated (unless the reviewer maintains it)

## STOP conditions

- The API's fields or the refusal for local Plan turns differ from "Current state".
- `codes show` doesn't print turn numbers that `--plan TURN` can refer to (then resolve by run id only, and say so).

## Maintenance notes

- If the API later allows local Plan turns, drop the `--cloud` requirement and the forced `location: cloud`.
