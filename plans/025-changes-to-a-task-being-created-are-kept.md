# Plan 025: Changes made to a task while it is still being created are kept

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/web/src/data/live.ts apps/web/src/overlays/Modals.tsx`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (ordering of writes)
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

A new task appears on the board at once, under a temporary key, while the server creates it. Anything the person does to it in that moment — rename it, move it to another column, star it, comment, delete it — is silently thrown away: the functions that send those changes return early for a temporary key, and show nothing. Dragging it sends a request for a key the server has never heard of and shows an error. On a slow connection the moment is long enough to hit by hand. After this plan those changes wait for the task to exist and are then sent under its real key, in order.

## Current state

`apps/web/src/data/live.ts`:

- `taskCreated(t)` gives the task a provisional key (`t.key = t.id = \`new-${uid("")}\``), shows a row under it, sends the create, and replaces the row with the API's (`addIssueRow`, `replaceIssueRow`). It registers its promise in a `creating` map:

```ts
const whenCreated = (t: Task) => creating.get(t.key) ?? Promise.resolve();
```

- `taskPatched` drops changes to a provisional task:

```ts
export function taskPatched(t: Task, keys: (keyof Task)[]) {
  if (!isLive() || t.key.startsWith("new-")) return;
```

- The same early return is in `taskStarred`, `tasksDeleted` (a `continue`) and `commentPosted` (search the file for `startsWith("new-")`).
- `taskRanked` has no such guard and sends `POST …/issues/new-…/rank`.
- One place already does it right: the attachment upload (`await whenCreated(t);` around line 856) and then looks the task up again.

Read `taskCreated` in full to see what `creating` maps from (the provisional key) and to (a promise resolving when the create finished), and how a caller learns the real key afterwards (the store's `task(id)` lookup, or a map from provisional to real key — if none exists, this plan adds one).

The repo's rule for these lists: "A slot keeps one list (and its objects) until the cached data changes, then builds new ones, so don't hold an item across an await (look it up again)."

`src/overlays/Modals.tsx` (around lines 225-229) toasts `Created ${t.key}` right after `createTask`, by which time `t.key` is the provisional `new-…` string.

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

- `apps/web/src/data/live.ts`
- `apps/web/src/data/live.test.ts` (create)
- `apps/web/src/overlays/Modals.tsx` (the toast text only)
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- The `write` helper's rollback and refetch behaviour (plan 026).
- Creating tasks in the sample workspace.
- Project creation and its starter issues.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/025-changes-to-a-task-being-created-are-kept origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: A way to act on the task once it exists

Next to `whenCreated`, add a map from provisional key to real key filled where `taskCreated` receives the API's answer, and a helper:

```ts
/** Run `send` once the task exists on the API, with the task as it is then (looked up again by its real key). */
const onceCreated = (t: Task, send: (real: Task) => void): void => {
  if (!t.key.startsWith("new-")) return send(t);
  const provisional = t.key;
  void whenCreated(t).then(() => {
    const key = realKeys.get(provisional);
    const real = key ? D().tasks.find((x) => x.key === key && x.project === t.project) : undefined;
    if (real) send(real);
  });
};
```

If the create failed, `realKeys` has no entry and the queued change is dropped — correct, since the task was removed with the failure's toast. Keep `realKeys` small: delete an entry a minute after it is set, or cap the map (say which you chose).

### Step 2: Queue instead of dropping

For each of `taskPatched`, `taskStarred`, `commentPosted`, `tasksDeleted` and `taskRanked`:

1. Keep the optimistic part (`show`) immediate, applied to the provisional row, so the person sees their change at once. `patchIssueRows(t, …)` already matches rows by key and project; it works on the provisional row.
2. Send through `onceCreated`, building the request from the **change** (the fields patched, the star, the comment text, the neighbour to rank against), not from a snapshot of the whole task taken before the await. After the create, the row was replaced by the API's version: re-apply the change to it (`show` again on the real key) before sending, so the refetch after the create doesn't visibly undo it.
3. Chain per task: two queued changes to the same provisional task must be sent in the order they were made (keep one promise chain per provisional key).

For `tasksDeleted` on a provisional task: remove its row at once, and after the create delete the real issue.

For `taskRanked` when the neighbour (`before` / `after`) is itself provisional, wait for both.

### Step 3: The toast

In `Modals.tsx`, when the key is provisional say `Created “${t.title}”` and drop the key from the message (the real key isn't known yet).

### Step 4: Tests

Create `src/data/live.test.ts` (`// @vitest-environment jsdom`). `live.ts` talks to the API through `api` from `lib/api.ts` and to the shared `queryClient`; mock `../../lib/api` with `vi.mock` so `api.POST` / `api.PATCH` / `api.DELETE` are spies returning `{ data, error: undefined, response: new Response() }` after a controllable delay (resolve a deferred promise by hand). Put the module in live mode the way the app does (read what `isLive()` checks and set that state in `beforeEach`; seed the issues query the functions patch). Cases:

1. Create, then patch the title before the create resolves → no PATCH is sent yet; after the create resolves, exactly one PATCH goes to the **real** key with the new title; the cached row shows the new title throughout.
2. Create, then star → one star request to the real key.
3. Create, then delete → the row disappears at once; after the create, one DELETE to the real key.
4. Create, then patch twice → two PATCHes in order.
5. Create fails → queued changes send nothing and nothing throws.
6. Rank a provisional task → no request names a `new-` key (assert over every spy call's path params).

If `live.ts` cannot be imported in a test without the whole app (it may import the router or components), STOP and report what blocks it rather than mocking half the app.

**Verify**: `pnpm --filter @dotrix/web test` → all pass; `pnpm typecheck && pnpm exec eslint . && pnpm format:check && pnpm knip --include files,dependencies,unlisted,unresolved,binaries` → exit 0

### Step 5: Changelog

Unreleased → Fixed: `- Renaming, moving, starring, commenting on or deleting a task in the moment after you add it is no longer lost.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- New file `src/data/live.test.ts` with the six cases in Step 4. Model the structure on `src/core/kaiWork.test.ts`; the mocking is new to this repo, so keep it in one helper at the top of the file.

## Done criteria

- [ ] `pnpm --filter @dotrix/web test` exits 0 with the six cases
- [ ] `grep -n 'startsWith("new-")) return' apps/web/src/data/live.ts` returns nothing (no silent drops left)
- [ ] Typecheck, ESLint, Prettier and knip exit 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- `live.ts` can't be imported under Vitest (see Step 4).
- The create's answer doesn't give the real key in a place `taskCreated` can record it.
- Re-applying a change after the create needs the `write` helper itself to change.

## Maintenance notes

- Any new sender in `live.ts` that takes a task must go through `onceCreated`; a reviewer should grep for direct uses of `t.key` in request paths.
- Plan 026 changes `write`'s rollback; land the two one after the other and re-run this file's tests after each.
