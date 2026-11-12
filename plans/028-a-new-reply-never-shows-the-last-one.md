# Plan 028: A new reply never starts by showing the previous reply's text

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/web/lib/agent.ts apps/web/lib/conversations.ts`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

While an agent answers, Chat shows the reply as it streams. The hook that holds the streamed text keeps it in state that is never cleared when the next run starts, so the next reply's bubble opens showing the whole previous answer until its own first words arrive, and the "thinking" indicator is hidden meanwhile because text is already present. In conversations across projects it is worse: if the stream drops it is never reconnected, so the stale text stays for the rest of the run. After this plan each run starts empty, and the cross-project stream reconnects like the project one.

## Current state

`apps/web/lib/agent.ts`, `useRunStream` (around lines 265-317):

```ts
export function useRunStream(scope: Scope | undefined, runId: string, active: boolean): RunStreamState {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [activity, setActivity] = useState<string | null>(null);
  const [thinking, setThinking] = useState("");
  // A dropped connection reconnects (the server sends the text so far again, from the run's kept
  // events if its live stream is gone), a little later each time.
  const [attempt, setAttempt] = useState(0);
  const failures = useRef(0);
  useEffect(() => {
    if (!scope || !active) return;
    let source: EventSource | undefined;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    void ensureSession().then(() => {
      ...
      stream.addEventListener("text", (e) => { setText(read(e as MessageEvent)); setThinking(""); });
      stream.addEventListener("delta", (e) => setText((t) => t + read(e as MessageEvent)));
      ...
      stream.addEventListener("open", () => (failures.current = 0));
      stream.onerror = () => {
        stream.close();
        if (!closed) retry = setTimeout(() => setAttempt((a) => a + 1), Math.min(1000 * 2 ** failures.current++, 15_000));
      };
    });
    return () => { closed = true; clearTimeout(retry); source?.close(); };
  }, [scope, runId, active, queryClient, attempt]);
  return { text, activity, thinking };
}
```

Nothing resets `text`, `thinking` or `activity` when `runId` changes. `src/screens/Chat.tsx` passes the working run's id (`working?.id`) and computes `busy = active && !stream.text`.

`apps/web/lib/conversations.ts`, `useCrossStream` (around lines 70-112) is a copy of the same hook for conversations across projects, with the same missing reset and no reconnect:

```ts
      stream.onerror = () => stream.close();
```

The server sends a `text` event with the text so far at the start of each connection, which is what makes reconnecting safe.

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

- `apps/web/lib/agent.ts`, `apps/web/lib/conversations.ts`
- `apps/web/lib/runStream.ts` (create: the shared part)
- `apps/web/src/core/runStream.test.ts` (create)
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- The server's stream endpoints.
- `src/screens/Chat.tsx` beyond what a changed return type forces (it should need no change).
- The coding session stream (`useCodingSessionStream` in `lib/coding.ts`).

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/028-a-new-reply-never-shows-the-last-one origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Share one implementation

Both hooks differ only in the stream's URL and in what they invalidate at the end. Move the body into `lib/runStream.ts` as `useEventStream({ url, key, active, onEnd })` returning `{ text, activity, thinking }`, where `key` identifies the run (reset when it changes) and `url` is `undefined` when the stream shouldn't open. `useRunStream` and `useCrossStream` become thin wrappers that build the URL and pass their existing end-of-run invalidations as `onEnd`. Keep their exported names and return types.

### Step 2: Reset per run

Keep the streamed state together with the run it belongs to, so stale state can never be returned:

```ts
const EMPTY = { text: "", thinking: "", activity: null as string | null };
const [state, setState] = useState({ key, ...EMPTY });
const current = state.key === key ? state : { key, ...EMPTY };
```

Return `current`'s fields, and have every event handler update with `setState((s) => (s.key === key ? {...} : { key, ...EMPTY, ...change }))`. This avoids a frame of old text that a reset inside `useEffect` would still show. Reset `failures.current` and the attempt counter's effect on the delay when `key` changes.

### Step 3: Reconnect everywhere

The shared hook keeps `useRunStream`'s backoff (`Math.min(1000 * 2 ** failures++, 15_000)`), so `useCrossStream` gains it. Keep `ensureSession()` before each connection and the `closed` guard.

### Step 4: Tests

Create `src/core/runStream.test.ts` (`// @vitest-environment jsdom`). Replace `globalThis.EventSource` with a small fake class that records instances and lets the test emit named events and errors. Render the hook with `renderHook` from `@testing-library/react` if that package is already a dev dependency of `apps/web` (`grep -n testing-library apps/web/package.json`); if it is not, do not add it: test instead a pure reducer extracted from the hook (`reduce(state, key, event)`) and say in your report that the hook's wiring is untested. Mock `ensureSession` to resolve at once. Cases:

1. Events for run A set the text; switching `key` to run B returns empty text on the very next render, before any event.
2. A late event from A's old stream after the switch does not change B's state.
3. A `text` event replaces the text and clears thinking; `delta` appends.
4. An error closes the stream and a new `EventSource` is created after the backoff (fake timers); the delay doubles and caps at 15 seconds; `open` resets it.
5. `end` closes the stream, calls `onEnd`, and no reconnect follows.
6. Unmount closes the stream and cancels a pending retry.

**Verify**: `pnpm --filter @dotrix/web test` → all pass; `pnpm typecheck && pnpm exec eslint . && pnpm format:check && pnpm knip --include files,dependencies,unlisted,unresolved,binaries` → exit 0

### Step 5: Changelog

Unreleased → Fixed: `- A new reply in Chat no longer opens showing the previous reply's text, and a reply in a conversation across projects keeps streaming after a dropped connection.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- New file `src/core/runStream.test.ts` with the six cases in Step 4.

## Done criteria

- [ ] `pnpm --filter @dotrix/web test` exits 0
- [ ] `grep -n "stream.onerror = () => stream.close()" apps/web/lib/conversations.ts` returns nothing
- [ ] `useRunStream` and `useCrossStream` keep their names, parameters and return shape (`git diff` on their call sites is empty)
- [ ] Typecheck, ESLint, Prettier and knip exit 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- The two hooks differ in more than the URL and the end-of-run invalidations.
- The cross-project stream endpoint does not resend the text so far on a new connection (reconnecting would then lose text): check the server's handler (`modules/agents/router.py`, `stream_workspace_run`) before enabling reconnect there, and report if it doesn't.

## Maintenance notes

- `useCodingSessionStream` in `lib/coding.ts` is a third stream with its own shape; it could move onto the shared hook later.
- A reviewer should check the `key` guard in every state update: it is what stops a late event from an old stream.
