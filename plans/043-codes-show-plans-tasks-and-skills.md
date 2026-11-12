# Plan 043: dotrix codes show prints a turn's plan, its parallel tasks, and the skills it used

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat ee73ad4..HEAD -- apps/cli/src/dotrix_cli/codes.py`
> If any of these changed, compare the "Current state" excerpts against the
> live code; on a mismatch in the lines this plan changes, treat it as a STOP
> condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 042 (shares codes.py; run after it)
- **Category**: feature
- **Planned at**: commit `ee73ad4`, 2026-11-12

## Why this matters

`dotrix codes show` prints a turn's request, its steps folded into one line, its summary, the files it
changed, the PR and CI. Since #254 and #258 a turn also carries:
- whether it was a Plan or a Build turn, and for a Plan turn the plan itself;
- for a Build turn split into parallel tasks, each task's status, attempt and checks;
- the skills it was given and the capabilities its engine had.

The web shows these in Codes. The terminal shows none of them, so a plan made from the CLI (plan 042)
can't be read there.

## Current state

- `apps/cli/src/dotrix_cli/codes.py` `echo_turn(turn, *, steps=False)` (line ~172) prints: the turn header with status and
  where it ran, `You: <note>`, the folded steps, the summary, an error, the changed files, then the PR
  and CI lines. It reads no `work_mode`, `plan_result`, `tasks`, `skills` or `capabilities`.
- `CodingRunRead` (`apps/backend/src/dotrix_backend/modules/coding/schemas.py:142`):
  - `work_mode: "plan" | "build"`, `plan_result: dict | None` with `title`, `summary`,
    `acceptance_criteria: list[str]`, `tasks: list[{title, detail, depends_on: list[int]}]`,
    `open_questions: list[str]`, `execution` (optional).
  - `tasks: list[{key, status, attempt, owned_paths, checks: list[dict], usage}]` (parallel coding,
    `DOTRIX_CODING_PARALLEL`, off by default).
  - `skills: list[{name, description, sha256, resources, missing_resources, unavailable_tools}]`.
  - `capabilities: list[{id, label, available, reason}]`.
- `test_show` in `apps/cli/tests/test_codes.py` shows the pattern: build a turn with `coding_run(...)`,
  `one_session(platform, ...)`, then assert on `codes(linked_repo, "show", "kun-7").output`.

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

- `apps/cli/src/dotrix_cli/codes.py` (`echo_turn` and the `show` command's options)
- `apps/cli/tests/test_codes.py`
- `CHANGELOG.md` (one line under Unreleased, in the existing section of its kind; never add a second heading)

**Out of scope** (do NOT touch):

- The API.
- `codes follow` (plan 042).
- The web app.

## Git workflow

- Work on the branch the reviewer gives you. Otherwise branch from `stage` and open the PR into `stage`, never `main`.
- Commit messages: one short sentence-case line.
- Do NOT push or open a PR unless instructed. Never use bare `git stash`.

## Steps

### Step 1: The kind of turn

In the turn header, a Plan turn reads `Turn 3 (a plan)`, like `(a revert)` today. A Build turn that
used a plan doesn't need marking.

### Step 2: A Plan turn's plan

When `plan_result` is set, print after the summary:
- its title (bold) and summary;
- `Acceptance criteria` as a list;
- `Tasks` numbered from 1, each with its title and `after 1, 2` when it has `depends_on`, and its `detail`
  indented and dimmed only with `--steps` (keep the default output short);
- `Open questions` when there are any.

End with a dim hint: `Build it: dotrix codes follow <KEY> "…" --plan <turn>` (plan 042's option).

### Step 3: Parallel tasks

When `tasks` is non-empty, print `Tasks` with one line each: key, status (the same colours as `_status`),
`attempt N` when above 1, and `checks passed` / `checks failed` from `checks` (count by each check's
`passed` or `status` key; read what the runner records in `modules/coding/parallel.py` and use that key).

### Step 4: Skills and capabilities, behind `--details`

Add `--details` to `show`. It prints the skills (name, and `missing: …` / `tools unavailable: …` when
those lists aren't empty) and the capabilities that are **not** available, with their reason. Without
the flag, print nothing for them: they are long and mostly the same every turn.

### Step 5: Changelog

Under Unreleased → Added: `- dotrix codes show prints a Plan turn's plan and a turn's parallel tasks; --details adds its skills and unavailable capabilities.`

## Test plan

In `test_codes.py`:

1. A Plan turn with a `plan_result` (two tasks, the second `depends_on: [1]`, one open question): `show` prints `(a plan)`, the title, the criteria, `2. … after 1`, the open question, and the build hint.
2. With `--steps`, a task's detail appears; without it, it doesn't.
3. A Build turn with two `tasks` (one `completed`, one `failed` with `attempt: 2`): both lines appear with their status and `attempt 2`.
4. `--details` lists a skill with `missing: …` and an unavailable capability with its reason; without `--details` neither appears.
5. A turn with none of these fields prints exactly what `test_show` expects today.

Every new test must fail on the code before your change. Check that (a temporary WIP commit, then the old source checked out) and say how in your report.

## Done criteria

- [ ] The five tests pass and fail before the change
- [ ] `uv run pytest apps/cli/tests -q` passes
- [ ] ruff clean
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` status row updated (unless the reviewer maintains it)

## STOP conditions

- The recorded check results in `parallel.py` have no field that says passed or failed (then print the check count only, and say so).

## Maintenance notes

- When the API adds fields to a turn, decide whether they belong in the default view or behind `--details`.
