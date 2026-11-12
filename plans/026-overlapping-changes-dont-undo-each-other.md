# Plan 026: Two quick changes to the same list don't undo each other

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/web/src/data/live.ts`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S–M
- **Risk**: MED (the helper every write uses)
- **Depends on**: plans/025-changes-to-a-task-being-created-are-kept.md (for its test file; can be done alone by creating the file)
- **Category**: bug
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

Every change in a real workspace is shown at once and then sent. When two changes to the same list are in flight together — dragging two cards quickly, ticking several subtasks — two things go wrong. If the first is refused, the app restores a snapshot taken before the first, which also wipes the second change from the screen although it may well succeed. And when the first finishes, the app refetches the list while the second is still on its way, so the server's answer (which doesn't include the second yet) briefly replaces it: the card jumps back, then forward. After this plan a refusal undoes only its own change, and the refetch waits until no change to those lists is still in flight.

## Current state

`apps/web/src/data/live.ts`, the `write` helper (around lines 76-103):

```ts
function write<T>(w: Write<T>): Promise<T | undefined> {
  let before: [QueryKey, unknown][] = [];
  const m = new MutationObserver<T, unknown, void>(queryClient, {
    mutationKey: ["write", ...w.refresh.slice(0, 1)],
    onMutate: async () => {
      await Promise.all(w.touches.map((k) => queryClient.cancelQueries({ queryKey: k })));
      before = w.touches.flatMap((k) => queryClient.getQueriesData({ queryKey: k }));
      w.show?.();
      render();
    },
    mutationFn: () => unwrap(w.request()),
    onSuccess: (r) => w.done?.(r),
    onError: (e) => {
      for (const [k, d] of before) queryClient.setQueryData(k, d);
      // A change the store made in place that never reached a cache goes too.
      forgetSlots();
      if (w.what) failed(w.what, e);
      w.undone?.();
      render();
    },
    onSettled: () => refresh(w.refresh),
  });
  return m.mutate().catch(() => undefined);
}
```

with

```ts
const refresh = (kinds: readonly string[]) => void queryClient.invalidateQueries({ predicate: (q) => kinds.includes(q.queryKey[0] as string) });
```

`Write<T>` has `what`, `touches` (query key prefixes), `show`, `request`, `refresh` (kinds of query), `done`, `undone`. The mutation key is the first refresh kind (`["write", "issues"]` for issue writes). Nothing in `src` or `lib` checks whether another write is in flight (`grep -rn isMutating apps/web/src apps/web/lib` finds nothing).

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

- `apps/web/src/data/live.ts` (the `write` helper and `refresh`)
- `apps/web/src/data/live.test.ts` (add cases; create it if plan 025 hasn't)
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- The individual senders (`taskPatched` and the rest) and their `show` functions.
- `data/account.ts` (Settings' saves).
- Making failed changes retry.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/026-overlapping-changes-dont-undo-each-other origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Refetch only when the last overlapping write settles

Track in-flight writes per kind of query in a module-level `Map<string, number>`: increment for each of `w.refresh` in `onMutate` (before the first `await`), decrement in `onSettled`. In `onSettled`, refetch only the kinds whose count is now zero. A kind still in flight will be refetched by the write that finishes last. Do not use `queryClient.isMutating({ mutationKey })` for this: the mutation key holds only the first refresh kind, and a write that refreshes `PROJECTS` also touches `issues`.

### Step 2: A refusal undoes only its own change

Restoring the whole pre-write snapshot is only safe when no other write to the same caches started after it. Change `onError`:

- If no other write to any of `w.touches`' kinds is in flight (the counters from Step 1, checked before decrementing this write's own), restore the snapshot as today.
- Otherwise do **not** restore the snapshot. Leave the caches as they are, and rely on the refetch that the last in-flight write triggers to bring the server's truth; show the failure toast as today and call `w.undone?.()`. Mark the touched kinds as needing a refetch even if the last write to settle didn't list them, so nothing stays wrong on screen: keep a `Set<string>` of kinds owed a refetch and flush it whenever a kind's counter reaches zero.

The result: a refused change may stay visible for the moment until the others settle, then the refetch corrects it. That is better than erasing changes that succeeded.

### Step 3: Tests

In `src/data/live.test.ts` (same mocking as plan 025; if that file doesn't exist, create it with the header `// @vitest-environment jsdom`, a `vi.mock` of `../../lib/api` whose methods return deferred promises you resolve or reject by hand, and live mode switched on as the app does). Use a spy on `queryClient.invalidateQueries`, and exercise `write` through two real senders on two different tasks (for example `taskPatched` twice):

1. Two writes in flight; the first resolves → no invalidation of `issues` yet; the second resolves → `issues` is invalidated once.
2. Two writes in flight; the first is rejected → the second task's optimistic change is still in the cache, and the failure toast for the first was raised (spy on `toast`); when the second resolves, `issues` is refetched.
3. One write alone, rejected → the cache is back to exactly what it was before (today's behaviour, unchanged).
4. One write alone, resolved → invalidated once (unchanged).

**Verify**: `pnpm --filter @dotrix/web test` → all pass; `pnpm typecheck && pnpm exec eslint . && pnpm format:check` → exit 0

### Step 4: Changelog

Unreleased → Fixed: `- Making several changes in quick succession (dragging cards, ticking subtasks) no longer makes one of them jump back for a moment, and a change that can't be saved no longer undoes the others on screen.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- Four cases in `src/data/live.test.ts` (Step 3).

## Done criteria

- [ ] `pnpm --filter @dotrix/web test` exits 0 with the four cases
- [ ] The counters are decremented on every path (success, failure) — case 3 and case 4 run twice in a row in one test without the second run's refetch being skipped
- [ ] Typecheck, ESLint and Prettier exit 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- `write` can't be exercised from a test without rendering the app.
- A sender depends on the snapshot being restored while another write is in flight (its `undone` assumes it): report the sender.

## Maintenance notes

- If a counter ever leaks (never returns to zero), its kind stops refetching: that is why Step 3's done criterion runs cases twice. A reviewer should look for any early return between the increment and `onSettled`.
- Deferred: per-item rollback (keeping an inverse patch per write) would undo a refused change immediately even with others in flight; this plan settles for correcting it at the next refetch.
