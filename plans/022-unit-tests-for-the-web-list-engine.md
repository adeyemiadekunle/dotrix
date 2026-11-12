# Plan 022: The web's list engine, routes and permissions have unit tests

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/web/src/shell/viewEngine.tsx apps/web/src/core/nav.ts apps/web/src/core/can.ts apps/web/src/data/markdown.ts`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (tests only)
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

The web app has seven unit-test files. The code that decides which tasks a list shows, in what order and under which heading, the code that turns a page into a URL and back, and the code that decides what a person may do have none; only slow browser tests touch them. Three known bugs sit in exactly that code (plans 023, 024 and 026 fix them), and fixing them safely needs tests that pin today's behaviour first. This plan adds those tests and changes no behaviour: where today's behaviour is a known bug, the test records it as `it.fails` with a pointer to the plan that fixes it.

## Current state

Files to cover, all in `apps/web/src`:

- `shell/viewEngine.tsx` — exports `matchF(task, filter)`, `sortTasks(tasks, sort)` and `groupTasks(tasks, group)` (read the file for exact signatures). `groupTasks` for `"assignee"` builds groups from `people()` plus "Unassigned"; for `"due"` it uses `matchF` with buckets `overdue`, `today`, `week`, `later`, `nodate`. `sortTasks` sorts by a key function per field, e.g. `estimate: (t) => t.estimate || "zzz"` (a string comparison).
- `core/nav.ts` — `Route`, `href(route, params)`, `routeOf(path)`: every page's URL.
- `core/can.ts` — `allowed(...)`, `canInvite()`, `approvalModes(...)`: what the signed-in person may do, from the permissions the API reports.
- `data/markdown.ts` — `mdToHtml`, `htmlToMd` (already has `data/markdown.test.ts`; this plan adds round-trip cases).

These read the store: `D()`, `S`, `people()`, `mem()`, `proj()` from `data/store.ts`, which builds the seeded sample workspace at import. Existing tests to model on: `core/utils.test.ts` (plain), `data/markdown.test.ts` (starts with `// @vitest-environment jsdom`), `core/kaiWork.test.ts`. Vitest picks up `src/**/*.test.{ts,tsx}` (`apps/web/vitest.config.ts`).

Known wrong behaviour today, which these tests must record without fixing:

1. Grouping by assignee drops any task whose assignee is not in `people()` — an agent (`agent:…`, e.g. a task Kai is coding) or a removed member.
2. Grouping by due date drops a done task whose due date is in the past: `overdue` excludes done tasks and no other bucket takes it.
3. Sorting by estimate compares strings, so `"10"` sorts before `"2"`.
4. `htmlToMd` drops a link's address and glues an `<h4>` heading to the next paragraph (the drawer's toolbar produces both), and `mdToHtml` output containing a double quote does not survive a round trip through the browser's `innerHTML` unchanged.

Repo conventions that apply (from the repository's `CLAUDE.md`): the web app is `apps/web` (Vite, React 19, TanStack Query); `src/` is the app and `lib/` holds the Query hooks; in a real workspace every write goes through `write` in `src/data/live.ts`, which changes the query cache first; a screen must work both in the seeded sample workspace (the local store) and a real one; UI copy is sentence case; Prettier's print width is 160; unit tests are Vitest files next to the code (`*.test.ts`, add `// @vitest-environment jsdom` on the first line when the code touches the DOM); every PR adds a line under `## [Unreleased]` in `CHANGELOG.md`, written for people who use dotrix.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `pnpm install` | exit 0 |
| Web unit tests (Vitest, `apps/web/src/**/*.test.ts`) | `pnpm --filter @dotrix/web test` | all pass |
| Typecheck | `pnpm typecheck` | exit 0 |
| Lint and format | `pnpm exec eslint . && pnpm format:check` | exit 0 |
| Unused files and dependencies | `pnpm knip --include files,dependencies,unlisted,unresolved,binaries` | exit 0 |
| Release check | `python scripts/release.py check` | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `apps/web/src/shell/viewEngine.test.tsx` (create)
- `apps/web/src/core/nav.test.ts` (create)
- `apps/web/src/core/can.test.ts` (create)
- `apps/web/src/data/markdown.test.ts` (add cases)

**Out of scope** (do NOT touch):

- Every non-test file. This plan changes no behaviour; plans 023, 024 and 026 do.
- `data/live.ts` (plan 025 adds its tests with the fix).
- Snapshot tests of rendered components.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/022-unit-tests-for-the-web-list-engine origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Find out how the modules load under test

Write a one-test file importing `groupTasks` and run it. If importing `data/store.ts` fails outside a browser (it may read `localStorage`), add `// @vitest-environment jsdom` on line 1, as `data/markdown.test.ts` does. Build tasks with a small local factory `task(over: Partial<Task>): Task` filled from the `Task` type in `data/types.ts`; take member ids from `people()` so they match the seeded store.

**Verify**: `pnpm --filter @dotrix/web test` → the placeholder passes

### Step 2: `viewEngine.test.tsx`

- `groupTasks(ts, "none")` → one group with every task.
- `"status"` and `"priority"` → every status / priority has a group, empty ones included, tasks in the right one.
- `"assignee"`: tasks of two members and one unassigned land in three groups; empty groups are omitted. Then `it.fails("keeps a task assigned to an agent (plan 023)", …)` asserting that a task with `assignee: "agent:kai"` appears in some group.
- `"due"`: one task per bucket lands in its bucket. Then `it.fails("keeps a done task whose due date has passed (plan 023)", …)`.
- `"project"`: tasks group by project.
- `sortTasks`: title (case-insensitive), due (undated last), priority (most urgent first), created and updated (newest first). Then `it.fails("sorts estimates as numbers (plan 023)", …)` with estimates `"2"` and `"10"`.
- `matchF`: `due` with `nodate`, `today`, `week`, `overdue`; `created` within N days; one `is` and one `is not` filter on status and on assignee. Read `matchF` and add a case per branch you find.

Every group or sort assertion compares task ids, not object identity.

### Step 3: `nav.test.ts`

For every member of `Route` (read the type; do not hard-code a count), with representative params: `routeOf(href(route, params))` gives back the same route and params. Add cases for a project key and a workspace slug containing a hyphen, a task opened through the search string, and an unknown path (whatever `routeOf` returns for it today: record it). If the round trip fails for a route today, record it with `it.fails` and name the route in your report.

### Step 4: `can.test.ts`

Read `can.ts` to see where permissions come from (the live workspace's reported permissions, or the sample's). Cover: an owner may do everything checked; a member without a permission may not; `canInvite()` is false in a personal workspace; `approvalModes` returns only modes at or below the cap, and what it returns for a cap value it doesn't know (record today's result; if it is an empty list, note it in your report as a possible bug without changing it).

### Step 5: Markdown round trips

In `data/markdown.test.ts` add: `htmlToMd(mdToHtml(md)) === md` for a paragraph, bold, code, a bulleted and a numbered list. Then, as `it.fails` with "(plan 024)" in the name: a link `<a href="https://example.com">site</a>` keeps its address; `<h4>Title</h4><p>Body</p>` keeps the heading on its own line; and `const el = document.createElement("div"); el.innerHTML = mdToHtml('say "hi"'); expect(el.innerHTML).toBe(mdToHtml('say "hi"'))`.

**Verify**: `pnpm --filter @dotrix/web test` → all pass (an `it.fails` test passes while the bug exists); `pnpm typecheck && pnpm exec eslint . && pnpm format:check` → exit 0

## Test plan

- This plan is the tests. Each `it.fails` must fail for the stated reason: turn each into a plain `it` once, confirm it fails with the expected values, then put `it.fails` back.

## Done criteria

- [ ] `pnpm --filter @dotrix/web test` exits 0; three new test files exist and `markdown.test.ts` has the new cases
- [ ] `git diff --stat` shows only `*.test.ts(x)` files
- [ ] Your report lists every `it.fails` and the plan that removes it
- [ ] Typecheck, ESLint and Prettier exit 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- A function named above doesn't exist or isn't exported, and testing it would need a change to a non-test file.
- More than the four known behaviours need `it.fails`: report the extra ones; they are new findings.

## Maintenance notes

- Plans 023, 024 and 026 each turn their `it.fails` cases into plain `it`; a reviewer should check none is left behind after them.
- `it.fails` passes while the bug exists and fails when it is fixed, so the fixer is forced to update the test.
