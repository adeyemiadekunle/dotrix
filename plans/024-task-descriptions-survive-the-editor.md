# Plan 024: Opening a task doesn't rewrite its description, and the editor keeps links and headings

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/web/src/data/markdown.ts apps/web/src/overlays/Drawer.tsx`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (changes how descriptions are saved)
- **Depends on**: plans/022-unit-tests-for-the-web-list-engine.md
- **Category**: bug
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

The task drawer shows a description by turning its Markdown into HTML, and saves by turning the edited HTML back into Markdown when the field loses focus. Two things go wrong. Any description containing a double quote is "changed" the moment someone clicks in and out, because the comparison is against text the browser has re-serialised: every such visit sends a save, adds an activity entry and refreshes the task lists. And the conversion back loses things the toolbar itself creates — a link's address disappears, a heading runs into the next paragraph — while nested lists and italics written by agents are flattened. After this plan a visit with no edit saves nothing, and what the editor can show it can save.

## Current state

`apps/web/src/data/markdown.ts`:

```ts
export function mdToHtml(md: string): string {
  const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
  const inline = (s: string) =>
    esc(s)
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/`(.+?)`/g, "<code>$1</code>");
  return md.trim().split(/\n{2,}/).map((block) => {
      const lines = block.split("\n");
      if (lines.every((l) => /^\s*[-*] /.test(l))) return `<ul>…</ul>`;
      if (lines.every((l) => /^\s*\d+\. /.test(l))) return `<ol>…</ol>`;
      return `<p>${lines.map(inline).join("<br>")}</p>`;
    }).join("");
}
```

`htmlToMd` walks the DOM and handles `B`/`STRONG`, `I`/`EM`, `CODE`, `BR`, `LI`, `UL`/`OL`, and `P`/`DIV`/`H1`/`H2`/`H3` (as a paragraph); anything else returns its children's text.

`apps/web/src/overlays/Drawer.tsx`, the `Rte` component (around lines 343-392):

```tsx
function Rte({ t, desc }: { t: Task; desc: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current && document.activeElement !== ref.current && ref.current.innerHTML !== desc) ref.current.innerHTML = desc;
  }, [desc]);
  ...
          onBlur={(e) => {
            const html = e.currentTarget.innerHTML;
            if (html !== desc) mutate(() => applyPatch(t, { desc: html }));
          }}
```

`desc` is HTML (from `mdToHtml` in a real workspace). A browser serialises a text node's `"` as a bare `"`, while `mdToHtml` wrote `&quot;`, so `html !== desc` is true with no edit. The toolbar (the `cmd(...)` buttons a few lines below) uses `document.execCommand` with `formatBlock` `h4` and `createLink`. In a real workspace the save converts with `htmlToMd` (`src/data/live.ts`: `body.description = htmlToMd(t.desc)`).

Plan 022 left `it.fails` cases for the link, the heading and the quote in `data/markdown.test.ts`.

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

- `apps/web/src/data/markdown.ts`, `apps/web/src/data/markdown.test.ts`
- `apps/web/src/overlays/Drawer.tsx` (the `Rte` component only)
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- Replacing the editor or adding a Markdown library to it (`components/markdown.tsx` renders Markdown elsewhere; the drawer's editor stays `contentEditable`).
- The backend, and how descriptions are stored (Markdown).
- Tables, images and code blocks in the editor: keep them as today (see Maintenance for the safety rule).

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/024-task-descriptions-survive-the-editor origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Don't save what wasn't edited

In `Rte`, remember what the element contained when it gained focus and compare against that:

```tsx
  const atFocus = useRef("");
  ...
          onFocus={(e) => (atFocus.current = e.currentTarget.innerHTML)}
          onBlur={(e) => {
            const html = e.currentTarget.innerHTML;
            if (html !== atFocus.current) mutate(() => applyPatch(t, { desc: html }));
          }}
```

If the element already has an `onFocus`, merge. The toolbar buttons change the content while focus may sit on a button: read how `cmd` restores focus and make sure a toolbar change still ends in a save (it should, since the content then differs from `atFocus.current` at the next blur; add a blur-less save only if you find a path that skips it).

Also stop escaping `"` in `mdToHtml`'s text (it is only needed inside attribute values, and this function writes none from user text until Step 2's links, which escape their own attribute): then `mdToHtml` output is stable through `innerHTML`.

### Step 2: Round-trip what the editor can produce

In `htmlToMd` add: `A` → `[text](href)` (only `http:`, `https:` and `mailto:` addresses; otherwise the text alone); `H1`–`H6` → `#`-prefixed lines (`H4` → `####`) followed by a blank line; nested `UL`/`OL` → items indented two spaces per level. In `mdToHtml` add: `[text](url)` → `<a href="…" target="_blank" rel="noopener noreferrer">text</a>` with the same scheme allowlist and the address attribute-escaped (`&`, `"`, `<`, `>`); `#`…`######` lines → `<h1>`…`<h6>`; `*italic*` and `_italic_` → `<i>` (after bold, and not inside code); indented list lines → nested lists.

Safety rule, with a test: `mdToHtml` must never emit a tag or attribute from the Markdown's own text. `mdToHtml('[x](javascript:alert(1))')` contains no `href`; `mdToHtml('<img src=x onerror=1>')` contains no `<img`.

### Step 3: Never flatten what the editor doesn't understand

Before saving, protect content the editor can't represent. In `Rte`'s blur handler, when `htmlToMd(mdToHtml(original)) !== original` for the Markdown the drawer was opened with (the description contains something this editor can't round-trip, such as a table or a fenced code block), do not overwrite: keep the editor read-only for that description and show one muted line under it — `This description has formatting the editor can't change here.` — using the existing `muted` class. Find where `Rte` gets its `desc` to obtain the original Markdown (the task's detail from `useTaskDetail`); if only HTML reaches `Rte`, pass the Markdown down as a second prop.

### Step 4: Tests

In `data/markdown.test.ts`: turn plan 022's three `it.fails` cases into plain `it`; add round trips (`htmlToMd(mdToHtml(md)) === md`) for a link, each heading level, italics, a two-level nested list, and a mix; the two safety cases from Step 2; and the stability check `el.innerHTML = mdToHtml(md); el.innerHTML === mdToHtml(md)` for text with quotes, ampersands and angle brackets.

**Verify**: `pnpm --filter @dotrix/web test` → all pass, no `it.fails` left mentioning plan 024; `pnpm typecheck && pnpm exec eslint . && pnpm format:check` → exit 0

### Step 5: Changelog

Unreleased → Fixed: `- Clicking into a task's description and out again no longer saves it when nothing changed, and the description editor keeps links, headings, italics and nested lists.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- The converted and added cases in `data/markdown.test.ts` (Step 4). The focus/blur behaviour needs a browser: if you can run `pnpm --filter @dotrix/web e2e -- --trace off` (needs Postgres), add one test to `e2e/board.spec.ts` that opens a task whose description contains a quote, clicks in and out, and asserts no PATCH to the issue was sent (`page.on("request")`); if you can't run it, say so and leave it out.

## Done criteria

- [ ] `pnpm --filter @dotrix/web test` exits 0
- [ ] `grep -n "plan 024" apps/web/src/data/markdown.test.ts` returns nothing
- [ ] The two safety cases exist and pass
- [ ] Typecheck, ESLint and Prettier exit 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- `data/markdown.test.ts` has no plan-022 cases (the dependency hasn't landed).
- The original Markdown can't reach `Rte` without changing files outside `Drawer.tsx`.
- A round trip changes a description used in an existing test or the seeded sample in a way that loses content.

## Maintenance notes

- The safety rule in Step 2 is the important review point: this function's output is assigned to `innerHTML`.
- Deferred: a real Markdown editor for descriptions; tables and code blocks in the drawer.
