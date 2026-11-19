# Plan 038: The desktop app opens only web links outside itself, and its window can't be sent to another site

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 7fb2b01..HEAD -- apps/desktop/src/main.ts apps/desktop/src/runner.ts`
> If any of these changed, compare the "Current state" excerpts against the
> live code; on a mismatch in the lines this plan changes, treat it as a STOP
> condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `7fb2b01`, 2026-11-12

## Why this matters

In the desktop app, any link that opens a new window is handed to the operating
system as it is. A link in content the app shows (a task description, a
comment, an agent's reply, a README excerpt) can therefore use a scheme other
than `https:`: `file:`, `smb:`, `ms-msdt:` or another app's custom protocol.
On Windows such links have been used to run programs or leak credentials. The
main window also has no rule against navigating away: a link without
`target=_blank` to another site would load that site inside the app's window.
The IPC bridge checks the caller's origin, so that page couldn't use the
runner, but it would sit in a trusted-looking window with the app's chrome.

## Current state

`apps/desktop/src/main.ts` (lines ~38-44):

```ts
  // Open external links in the system browser, never inside the app window.
  win.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });

  void win.loadURL(WEB_URL);
```

There is no `will-navigate` or `will-redirect` handler anywhere in `apps/desktop/src` (`grep -rn "will-navigate" apps/desktop/src` finds nothing).
`apps/desktop/src/runner.ts:161` also calls `shell.openExternal(url)` in the device sign-in window; read where that `url` comes from.
`main.ts` already has `sameOrigin(a, b)` (used by the IPC `handle` wrapper) and `WEB_URL`.
GitHub sign-in and the GitHub App install are top-level redirects through `/api/auth/github` and `/api/github/*` on the app's own origin, which then go to `github.com` and come back.

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

- `apps/desktop/src/main.ts`, `apps/desktop/src/runner.ts`
- a new `apps/desktop/src/links.ts` with the pure decision functions and its unit test (use the test runner the desktop package already has; if it has none, add a Vitest file only if `apps/desktop/package.json` can run it without new dependencies, else test the functions from `apps/web`'s Vitest is NOT acceptable: STOP and report)
- `CHANGELOG.md` (one line under Unreleased, in the existing section of its kind; never add a second heading)

**Out of scope** (do NOT touch):

- The IPC bridge and preload.
- The web app.
- Auto-update.

## Git workflow

- Work on the branch the reviewer gives you. Otherwise branch from `stage` and open the PR into `stage`, never `main`.
- Commit messages: one short sentence-case line.
- Do NOT push or open a PR unless instructed. Never use bare `git stash`.

## Steps

### Step 1: Pure rules, tested

`links.ts`:

- `opensOutside(url: string): boolean` is true only for a parsable URL whose protocol is `https:`, or `http:` when the host is `localhost` or `127.0.0.1` (development), or `mailto:`.
- `staysInside(url: string, appUrl: string): boolean` is true when the URL has the app's origin, or is one of the sign-in hosts the app's own redirects pass through: `github.com` (paths starting `/login` or `/apps/` or `/settings/installations`). Read `modules/web` and `modules/connectors` routes for the exact GitHub URLs the redirects use and list them in a comment; if there are others (Google sign-in is planned, not built), don't add them.

### Step 2: Use them

- `setWindowOpenHandler`: `if (opensOutside(url)) void shell.openExternal(url);` and always `deny`.
- Add `win.webContents.on("will-navigate", (event, url) => { if (!staysInside(url, WEB_URL)) { event.preventDefault(); if (opensOutside(url)) void shell.openExternal(url); } })` and the same for `will-redirect`.
- `runner.ts:161`: pass through `opensOutside` too, and apply the same navigation rule to the sign-in window if it is a `BrowserWindow` that loads the web app.

**Verify**: `pnpm --filter @dotrix/desktop build` (or its typecheck script) passes.

### Step 3: Changelog

Under Unreleased → Security: `- The desktop app opens only web and email links in your browser, and its window stays on dotrix (and GitHub's sign-in pages).`

## Test plan

Unit tests for `links.ts`:

1. `opensOutside`: `https://example.com` true; `http://localhost:3000` true; `http://example.com` false; `file:///etc/passwd`, `smb://host/share`, `ms-msdt:/id`, `javascript:alert(1)`, `vscode://x`, an unparsable string: all false; `mailto:a@b.c` true.
2. `staysInside`: the app's origin with any path true; another origin false; `https://github.com/login/oauth/authorize?...` true; `https://github.com/someone/repo` false; `https://github.com.evil.example/login` false.

Manual, if you can run Electron here (say if you can't): GitHub sign-in still completes in the app window.

Every new test must fail on the code before your change. Check that (a temporary WIP commit, then the old source checked out) and say how in your report.

## Done criteria

- [ ] The unit tests pass
- [ ] `grep -n 'openExternal' apps/desktop/src -r` shows every call guarded by `opensOutside`
- [ ] the desktop package's build/typecheck passes; `pnpm format:check`, `pnpm lint` exit 0
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` status row updated (unless the reviewer maintains it)

## STOP conditions

- GitHub sign-in or the App install passes through a host or path the rule would block and you can't enumerate them from the code.
- The desktop package has no way to run a unit test without adding dependencies.

## Maintenance notes

- A new sign-in provider (Google is planned) needs its hosts added to `staysInside`, or its redirect opened in the system browser.
- Not covered here and worth a later look: `desktop.yml` and action pinning are plan 039; the reviewers' lead that the app can hang on quit is unverified.
