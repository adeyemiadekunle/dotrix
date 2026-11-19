# Plan 027: A brief network failure doesn't replace the workspace with an error or sign you out

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/web/src/shell/StoreBridge.tsx apps/web/lib/api.ts`
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

Two places treat a passing failure as fatal. The shell replaces the whole workspace with "The workspace didn't load" when one of three background refetches fails, even though the data is already on screen: waking a laptop is enough, and an open task or a half-written message is lost. And when a request gets a 401 and the session refresh then fails for any reason at all — a 500, a proxy timeout, a rate limit — the app sends the person to the sign-in page, although their session may be perfectly valid. After this plan only a workspace that never loaded shows the error screen, and only a refresh the server actually refuses signs the person out.

## Current state

`apps/web/src/shell/StoreBridge.tsx` (around lines 44-51 and 75-82):

```tsx
  const dirFailed = useDirectoryFailed(wsId);
  useEffect(() => {
    if (wsId && dirFailed && live.mode === "live") {
      live.mode = "error";
      live.error = "Some of the workspace didn't load.";
      render();
    }
  }, [wsId, dirFailed]);
...
function useDirectoryFailed(wsId: string | undefined): boolean {
  const client = useQueryClient();
  const subscribe = useCallback((onChange: () => void) => client.getQueryCache().subscribe(onChange), [client]);
  return useSyncExternalStore(
    subscribe,
    () => Boolean(wsId) && ["members", "projects", "agents"].some((kind) => client.getQueryState([kind, wsId])?.status === "error"),
  );
}
```

In TanStack Query v5 a failed **background refetch** sets `status: "error"` while keeping the previous `data`. `src/shell/Studio.tsx` (around lines 185-193) renders the error screen when `live.mode === "error"`.

`apps/web/lib/api.ts` (around lines 22-62):

```ts
async function refreshSession(sentAt: number): Promise<boolean> {
  const run = async () => {
    const last = Number(localStorage.getItem(REFRESHED_AT) ?? 0);
    if (last > sentAt) return true; // refreshed meanwhile: the cookies are already new
    const response = await fetch("/api/auth/refresh", { method: "POST", headers: WEB_HEADER });
    if (!response.ok) return false;
    ...
  };
  ... navigator.locks ? navigator.locks.request(…, run) : run() ...
}
...
  const sentAt = Date.now();
  const response = await fetch(request);
  if (response.status !== 401) return response;
  if (!(await refreshSession(sentAt))) {
    toSignIn();
    return response;
  }
```

Read the whole file: `fetch` to the refresh endpoint can also throw (offline), and without `navigator.locks` (an insecure non-localhost origin, an old browser) several simultaneous 401s each run their own refresh with the same refresh token, which the backend treats as reuse.

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

- `apps/web/src/shell/StoreBridge.tsx`
- `apps/web/lib/api.ts`
- `apps/web/src/core/session.test.ts` (create; tests for the refresh logic, importing from `../../lib/api`)
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- The backend's refresh endpoint and its reuse detection.
- Retry policy in `lib/queryClient.ts`.
- An offline banner or a reconnect indicator (a possible follow-up).

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/027-a-network-blip-doesnt-eject-you origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Only a workspace that never loaded is an error

In `useDirectoryFailed`, a query counts as failed only when it has no data:

```ts
    () =>
      Boolean(wsId) &&
      ["members", "projects", "agents"].some((kind) => {
        const state = client.getQueryState([kind, wsId]);
        return state?.status === "error" && state.data === undefined;
      }),
```

Nothing else in the effect changes. A failed background refetch then leaves the screen as it is; the next refetch (window focus, reconnect, the next write) tries again.

### Step 2: Three outcomes for a refresh, not two

Make `refreshSession` return `"ok" | "refused" | "unavailable"`:

- `"ok"`: the refresh succeeded, or another tab refreshed meanwhile.
- `"refused"`: the endpoint answered 401 or 403 — the session is really over.
- `"unavailable"`: anything else (another status, or `fetch` threw).

In the caller: on `"ok"` retry the request as today; on `"refused"` call `toSignIn()` as today; on `"unavailable"` return the original 401 response **without** redirecting — the caller's error handling shows its usual failure, and the next request tries the refresh again. Read how callers treat a 401 response (`unwrap`, the Query hooks) and make sure this path cannot loop: one refresh attempt per request, as today.

### Step 3: One refresh at a time in this tab, with or without Web Locks

Add a module-level `let pending: Promise<…> | null` so that concurrent callers in the same tab share one refresh whether or not `navigator.locks` exists (the lock still serialises across tabs when available):

```ts
let pending: ReturnType<typeof runRefresh> | null = null;
const refreshOnce = (sentAt: number) => (pending ??= runRefresh(sentAt).finally(() => (pending = null)));
```

Keep the `REFRESHED_AT` check inside, so a caller whose request was sent before a refresh that has since completed doesn't refresh again.

### Step 4: Tests

Create `src/core/session.test.ts` (`// @vitest-environment jsdom`), stubbing `globalThis.fetch` with `vi.fn()` and `location.assign` (or whatever `toSignIn` calls: read it) with a spy. Export from `lib/api.ts` only what the test needs (`apiFetch` is already exported; avoid exporting internals if the behaviour can be driven through it). Cases:

1. Request → 401, refresh → 200, retry → 200: the caller gets 200; no redirect.
2. Request → 401, refresh → 401: redirect to sign-in.
3. Request → 401, refresh → 503: **no** redirect; the caller gets the 401 response.
4. Request → 401, refresh rejects (network error): no redirect; nothing throws from the refresh path.
5. Five requests → 401 at once with `navigator.locks` undefined: exactly one call to the refresh endpoint, and all five are retried.

For Step 1, the logic is a pure predicate over query states: extract it as a small exported function `directoryFailed(states)` in `StoreBridge.tsx` (or a neighbouring file) and test it directly: error without data → true; error with data → false; pending → false.

**Verify**: `pnpm --filter @dotrix/web test` → all pass; `pnpm typecheck && pnpm exec eslint . && pnpm format:check && pnpm knip --include files,dependencies,unlisted,unresolved,binaries` → exit 0

### Step 5: Changelog

Unreleased → Fixed: `- A brief loss of connection (waking a laptop, a server restart) no longer replaces the workspace with an error screen or sends you to sign in again.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- New file `src/core/session.test.ts` (five cases) and the predicate test (Step 4).

## Done criteria

- [ ] `pnpm --filter @dotrix/web test` exits 0 with the new cases
- [ ] `grep -n 'if (!response.ok) return false' apps/web/lib/api.ts` returns nothing
- [ ] Typecheck, ESLint, Prettier and knip exit 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- A caller relies on being redirected for any failed refresh (for example a loop that polls and would now poll forever on 401): report it.
- `toSignIn` can't be observed in a test without changing its behaviour.

## Maintenance notes

- If the API is ever scaled to several processes, the in-tab single flight added here is what keeps one tab from presenting the same refresh token twice.
- Follow-up: a small "reconnecting" notice when a background refetch fails with data on screen.
