# Plan 020: Approving in Chat or Codes refreshes the task lists straight away

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/web/lib/agent.ts apps/web/lib/coding.ts apps/web/lib/issues.ts`
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

When someone approves an agent's change in Chat, or approves a coding turn in Codes, the task it touches changes on the server: its status, its assignee. The board, the lists and the task drawer keep showing the old values until something else refreshes them, because the two hooks invalidate a query key the task lists don't use. After this plan those screens update as soon as the approval settles.

## Current state

The task lists read workspace-wide issue queries whose keys start `["issues", "workspace", <workspaceId>, …]` (`apps/web/lib/issues.ts` `useWorkspaceIssues`: `queryKey: ["issues", "workspace", workspaceId, filters]`; `apps/web/lib/store-slots.ts` reads `["issues", "workspace", ws, EVERY_ISSUE]`). Per-project keys are `issueKeys` in `lib/issues.ts`:

```ts
export const issueKeys = {
  all: (s: Scope) => ["issues", s.projectId] as const,
  ...
  issue: (s: Scope, key: string) => ["issues", s.projectId, "issue", key] as const,
};
```

`apps/web/lib/agent.ts`, `useAgentMutation` (around lines 160-170):

```ts
    onSettled: async () => {
      if (!scope) return;
      await queryClient.invalidateQueries({ queryKey: agentKeys.project(scope) });
      await queryClient.invalidateQueries({ queryKey: ["approvals", scope.workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["notifications", scope.workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["threads", scope.workspaceId] });
      // Approved actions may have changed issues or files.
      await queryClient.invalidateQueries({ queryKey: ["issues", scope.projectId] });
    },
```

`apps/web/lib/coding.ts`, `useCodingMutation` (around lines 78-86):

```ts
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
      // Approving assigns the issue to the coding tool and moves it to in progress.
      void queryClient.invalidateQueries({ queryKey: ["issues", scope?.projectId] });
```

`["issues", projectId]` is not a prefix of `["issues", "workspace", …]`, so the lists are never invalidated. The run stream's `end` handler in `lib/agent.ts` (`useRunStream`, the `stream.addEventListener("end", …)` block) invalidates runs, approvals, notifications and threads, and not issues, although a finished run may have changed tasks under Accept edits or Auto.

`Scope` is `{ workspaceId, projectId }`.

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

- `apps/web/lib/agent.ts`, `apps/web/lib/coding.ts`
- `apps/web/lib/issues.ts` (one exported key helper)
- `apps/web/lib/issues.test.ts` (create)
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- `src/data/live.ts` and its `ISSUES` refresh list: those are the store's own writes.
- Changing any query's key.
- Knowledge/document invalidation after approved file changes (a separate gap; see Maintenance).

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/020-approvals-refresh-the-board origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: One helper that names both families of issue query

In `lib/issues.ts` add and export:

```ts
/** Every issues query a change in this project can show up in: the project's own and the workspace-wide lists. */
export const issueQueriesOf = (s: Scope) => [issueKeys.all(s), ["issues", "workspace", s.workspaceId] as const] as const;
```

### Step 2: Use it in the three places

- `useAgentMutation.onSettled`: replace the single `["issues", scope.projectId]` invalidation with a loop over `issueQueriesOf(scope)`.
- `useCodingMutation`: the same, guarded by `if (scope)` (its current code tolerates an undefined scope; keep that tolerance).
- `useRunStream`'s `end` handler: add the same loop after the existing invalidations.

### Step 3: Test the helper against the real keys

Create `lib/issues.test.ts`. Vitest's include pattern is `src/**/*.test.{ts,tsx}` (`apps/web/vitest.config.ts`), so either place the test at `src/data/issueKeys.test.ts` importing from `../../lib/issues`, or extend the include pattern to `lib/**/*.test.ts` — prefer the first, and name the file accordingly in your report. With a `QueryClient` from `@tanstack/react-query`: seed data under `["issues", "workspace", "w1", { archived: "include" }]`, `["issues", "p1", "all"]` and `["issues", "workspace", "w2", {}]`; invalidate each key from `issueQueriesOf({ workspaceId: "w1", projectId: "p1" })`; assert the first two are now `isInvalidated` (`client.getQueryState(key)?.isInvalidated`) and the third (another workspace) is not.

**Verify**: `pnpm --filter @dotrix/web test` → all pass, including the new file

### Step 4: Checks and changelog

CHANGELOG → Unreleased → Fixed: `- After you approve an agent's change in Chat or a coding turn in Codes, the board, the lists and the open task show the new status and assignee at once.`

**Verify**: `pnpm typecheck && pnpm exec eslint . && pnpm format:check` → exit 0; `python scripts/release.py check` → exit 0

## Test plan

- One new Vitest file (Step 3). The hooks themselves need a browser; the browser tests (`pnpm --filter @dotrix/web e2e`, needs Postgres) cover approvals in `e2e/approvals.spec.ts` — run it if your environment can, and say whether you did.

## Done criteria

- [ ] `pnpm --filter @dotrix/web test` exits 0 with the new test
- [ ] `grep -n '\["issues", scope' apps/web/lib/agent.ts apps/web/lib/coding.ts` returns nothing (both use the helper)
- [ ] Typecheck, ESLint and Prettier exit 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- The workspace-wide issue queries no longer start with `["issues", "workspace", workspaceId]`.
- `knip` reports the new export as unused (it should be used three times).

## Maintenance notes

- Any new mutation that can change a task from outside `src/data/live.ts` should invalidate `issueQueriesOf(scope)`.
- Related gap, not fixed here: approved file changes don't invalidate the knowledge and document queries either.
