# Plan 023: Grouped and sorted task lists show every task, in the right order, with its comment count

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/web/src/shell/viewEngine.tsx apps/web/src/components/TaskList.tsx`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/022-unit-tests-for-the-web-list-engine.md
- **Category**: bug
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

A task list grouped by assignee silently leaves out every task assigned to an agent — which is exactly what happens to a task when Kai starts coding it — and every task assigned to someone no longer in the workspace. Grouped by due date, a finished task whose date has passed vanishes. Sorted by estimate, 10 comes before 2. And in a real workspace the list never shows comment counts, while the board does. People make decisions from these lists; work that isn't shown gets forgotten.

## Current state

`apps/web/src/shell/viewEngine.tsx`, `groupTasks` (around lines 134-166):

```tsx
  else if (g === "assignee")
    groups = [
      ...people().map((m) => ({ key: m.id, name: m.name, html: <Av id={m.id} cls="sm" tip={false} />, set: { assignee: m.id } })),
      { key: "none", name: "Unassigned", html: <Av id={null} cls="sm" tip={false} />, set: { assignee: null } },
    ];
  ...
  else
    groups = [
      { key: "overdue", name: "Overdue" },
      { key: "today", name: "Today" },
      { key: "week", name: "Next 7 days" },
      { key: "later", name: "Later" },
      { key: "nodate", name: "No due date" },
    ].map((x) => ({ ...x, html: <Ic n="calendar" s={14} /> }));
  const out = groups.map((G) => ({
    ...G,
    tasks: ts.filter((t) => {
      if (g === "assignee") return (t.assignee || "none") === G.key;
      if (g === "due") return matchF(t, { f: "due", op: "is", v: [G.key] });
      return String((t as unknown as Record<string, unknown>)[g]) === G.key;
    }),
  }));
  return g === "status" || g === "priority" ? out : out.filter((G) => G.tasks.length);
```

`matchF`'s due branch (around lines 84-89): `v === "overdue" ? isOver(t) : v === "today" ? n === 0 : v === "week" ? n >= 0 && n <= 7 : n > 7` — a past date on a done task matches none (`isOver` excludes done tasks).

`sortTasks`' key for estimates: `estimate: (t: Task) => t.estimate || "zzz"`.

`apps/web/src/components/TaskList.tsx:119`: `const cc = commentsOf(t.id).length;` — `commentsOf` reads `D().comments`, which is the sample workspace's local list and empty in a real workspace. The board uses `commentCount(t)` from `data/tasks.ts` (`views/Board.tsx:17`), which works in both.

`who(id)` in `data/store.ts` resolves a member **or** an agent to something with a name; `Av` renders either. Plan 022 left `it.fails` tests for the first three behaviours in `shell/viewEngine.test.tsx`.

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

- `apps/web/src/shell/viewEngine.tsx`
- `apps/web/src/components/TaskList.tsx` (the comment count only)
- `apps/web/src/shell/viewEngine.test.tsx`
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- Filters (`matchF`'s semantics for the filter bar): a filter for "overdue" still means not done and past due.
- The board's columns.
- Dragging a task onto a group (the `set` each group carries): agent and removed-member groups get no `set`.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/023-grouped-lists-show-every-task origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Assignee groups for everyone who has tasks

After building the people groups, append a group for each distinct `t.assignee` among `ts` that is not `null` and not one of the people's ids, in order of first appearance: `key` = the assignee id, `name` = `who(id)?.name ?? "Former member"`, `html` = `<Av id={id} cls="sm" tip={false} />`, and no `set` (a list row can't be dragged onto it to reassign). Keep "Unassigned" last.

### Step 2: A bucket for finished, past-due tasks

In the due grouping only (not in `matchF`), assign each task to exactly one bucket with a local function: no date → `nodate`; date before today and not done → `overdue`; date before today and done → `past`; today → `today`; within 7 days → `week`; else `later`. Add the group `{ key: "past", name: "Past" }` after "Later" and before "No due date". Every dated or undated task must land in exactly one bucket.

### Step 3: Numeric estimates

Sort estimates by number: `estimate: (t) => (t.estimate ? parseFloat(t.estimate) : Number.POSITIVE_INFINITY)`. Check how the comparator handles mixed string and number keys (read the `sort` callback just below the table) and keep tasks without an estimate last; if an estimate can be non-numeric text (read the `Task` type and where estimates are entered), sort those after the numeric ones by text.

### Step 4: Comment count from the same source as the board

In `TaskList.tsx` replace `commentsOf(t.id).length` with `commentCount(t)` imported from `../data/tasks`, and drop `commentsOf` from the store import if nothing else in the file uses it.

### Step 5: Tests

In `shell/viewEngine.test.tsx` turn the three `it.fails` cases from plan 022 into plain `it`, and add: every task in the input appears in exactly one group, for each of `assignee`, `due`, `project`, `status`, `priority` (a property-style check over a mixed list including an agent assignee, a removed-member id, a done past-due task and an undated one); the agent group is named after the agent; "Unassigned" stays last.

**Verify**: `pnpm --filter @dotrix/web test` → all pass, with no `it.fails` left mentioning plan 023; `pnpm typecheck && pnpm exec eslint . && pnpm format:check && pnpm knip --include files,dependencies,unlisted,unresolved,binaries` → exit 0

### Step 6: Changelog

Unreleased → Fixed: `- A task list grouped by assignee now shows tasks assigned to an agent (such as one Kai is coding) and to people who have left; grouped by due date it keeps finished tasks whose date has passed; estimates sort as numbers; and lists show comment counts in every workspace.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- The converted and added cases in `shell/viewEngine.test.tsx` (Step 5).

## Done criteria

- [ ] `pnpm --filter @dotrix/web test` exits 0
- [ ] `grep -n "plan 023" apps/web/src/shell/viewEngine.test.tsx` returns nothing
- [ ] `grep -n "commentsOf" apps/web/src/components/TaskList.tsx` returns nothing
- [ ] Typecheck, ESLint, Prettier and knip exit 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- `shell/viewEngine.test.tsx` doesn't exist (plan 022 hasn't landed).
- `who()` can't resolve an agent's id to a name in a real workspace.

## Maintenance notes

- The "exactly one group" test is the guard for any new grouping added later.
- Deferred: letting a row be dragged onto an agent's group to assign it (assigning Kai has its own rules in Build mode).
