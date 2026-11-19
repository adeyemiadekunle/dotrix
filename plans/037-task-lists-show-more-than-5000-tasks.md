# Plan 037: A workspace with more than 5,000 tasks shows all of them

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 7fb2b01..HEAD -- apps/web/lib/issues.ts apps/backend/src/dotrix_backend/modules/issues/router.py`
> If any of these changed, compare the "Current state" excerpts against the
> live code; on a mismatch in the lines this plan changes, treat it as a STOP
> condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MEDIUM
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `7fb2b01`, 2026-11-12

## Why this matters

The web app asks for a workspace's or a project's tasks in one request with
`limit: 5000`, the API's maximum. Past that, the remaining tasks are simply
missing: not on the board, not in lists, not in counts, with nothing on screen
saying so. A long-lived workspace with done and archived work gets there.

## Current state

`apps/web/lib/issues.ts`:

```ts
// line ~58, useWorkspaceIssues
          params: { path: { workspace_id: workspaceId! }, query: { ...filters, limit: 5000 } },
// line ~73, the project's issues
          params: { path: path(scope!), query: { order: "rank", limit: 5000 } },
```

`apps/backend/src/dotrix_backend/modules/issues/router.py`: three list routes declare `limit: int = Query(default=500, ge=1, le=5000)` and `offset: int = Query(default=0, ge=0)` (lines ~98, ~129, ~346). They return a plain list, with no total.
Since 2026-11-10 the store's task lists in a real workspace are these query caches (`apps/web/lib/store-slots.ts`), and writes patch the cached rows (`patchIssueRows`, `addIssueRow` in `apps/web/src/data/live.ts`), so the cache must stay one flat array per query key.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend tests | `uv run pytest apps/backend/tests -q -k "<the tests you add>"` | pass |
| Lint | `uv run ruff check apps packages` | All checks passed |
| Release check | `python scripts/release.py check` | exit 0 |
| Format | `pnpm format:check` | exit 0 |

Integration tests need Postgres and Redis (`pnpm db:up`) and the `DOTRIX_*` test variables described in `CLAUDE.md`.

## Scope

**In scope**:

- `apps/web/lib/issues.ts`
- a unit test beside it or in `apps/web/src/data/`
- `apps/backend/src/dotrix_backend/modules/issues/service.py` or `repository.py` only if Step 1 finds an unstable order
- `CHANGELOG.md` (one line under Unreleased, in the existing section of its kind; never add a second heading)

**Out of scope** (do NOT touch):

- The API's limit and response shape (no pagination envelope in this plan).
- `store-slots.ts`, `live.ts` and the screens: they keep reading one array.
- Virtualizing long lists.

## Git workflow

- Work on the branch the reviewer gives you. Otherwise branch from `stage` and open the PR into `stage`, never `main`.
- Commit messages: one short sentence-case line.
- Do NOT push or open a PR unless instructed. Never use bare `git stash`.

## Steps

### Step 1: Check the order is stable

Paging by offset needs a total order. For each of the three routes read the `ORDER BY` in the service: if it can tie (two issues with the same due date, priority or rank), add the issue id as the last sort key. That is the only backend change allowed. **Verify**: the issues integration tests pass.

### Step 2: Fetch every page

In `lib/issues.ts` add `fetchAllIssues(fetchPage: (offset: number) => Promise<T[]>, pageSize = 1000): Promise<T[]>`: it requests pages until one comes back shorter than `pageSize`, concatenates them, and drops any id seen before (an insert between pages can shift rows). Use it in both `queryFn`s with `limit: 1000`. Keep each query key and the returned type as they are. Stop after 50 pages (50,000 tasks) and log a console warning: a guard, not a limit anyone should meet.

### Step 3: Changelog

Under Unreleased → Fixed: `- A workspace or project with more than 5,000 tasks now shows all of them.`

## Test plan

Unit tests for `fetchAllIssues` (Vitest, no network):

1. One short page: one request.
2. Exactly `pageSize` rows then an empty page: two requests, all rows.
3. Three pages: order kept, offsets `0, 1000, 2000`.
4. A row repeated across two pages appears once.
5. The 50-page guard stops and warns.

Backend, only if Step 1 changed an order: two issues tied on the sort key come back in the same order on two requests with `limit=1, offset=0/1`.

Every new test must fail on the code before your change. Check that (a temporary WIP commit, then the old source checked out) and say how in your report.

## Done criteria

- [ ] `grep -n 'limit: 5000' apps/web/lib/issues.ts` finds nothing
- [ ] `pnpm --filter @dotrix/web test` and `pnpm typecheck` pass
- [ ] `pnpm exec eslint apps/web/lib` clean; `pnpm format:check` exit 0; `pnpm knip` clean
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` status row updated (unless the reviewer maintains it)

## STOP conditions

- A list route's order can't be made total without changing what people see first.
- Something else in the web calls these endpoints with `limit: 5000` and isn't covered (grep `limit: 5000` across `apps/web`).

## Maintenance notes

- This keeps loading everything; it only removes the silent cut-off. If first load gets slow, the next step is a paged API with a total and lists that load on scroll, which is a larger change touching `store-slots.ts`.
