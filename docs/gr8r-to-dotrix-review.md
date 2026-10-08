# Review: bringing Gr8r Studio into Dotrix (and moving the web app to Vite)

Date: 2026-10-08. Compared: `gr8r-studio` @ `904205c` (Vite, vanilla JS, ~13.9k lines) and Dotrix
`main` @ `fda1cda` (`apps/web`: Next.js 16, React 19, shadcn/ui, ~14.2k lines of components and lib,
77 route files).

**Goal:** Dotrix's web app looks and works like Gr8r Studio, keeps everything Gr8r doesn't have
(Chat, Knowledge, agents, approvals, coding sessions, the graph, automations), and is built with
Vite instead of Next.js.

## 1. Summary

- Gr8r is a finished **front-end prototype**. All its data is seeded into `localStorage`
  (`core/store.js`, `data/seed.js`): no API, no accounts, no permissions. Dotrix has the real
  backend, so this is not "move the code over". It means **rebuilding Gr8r's screens in Dotrix's
  React app, against Dotrix's API**, and adding the backend pieces Gr8r assumes but Dotrix lacks.
- **Don't copy Gr8r's JavaScript literally.** Its pages are functions returning HTML strings, with
  one global store and a `data-a="action"` click table (`actions/actions.js` alone is 2,293 lines).
  Copying that into Dotrix would throw away React Query caching, the typed API client, role-aware
  controls, and the hydration and URL-state rules. **What carries over directly:** Gr8r's design
  (tokens, spacing, type, motion: `styles/*.css`, ~5k lines), its layouts, its copy and empty
  states, and its interaction designs. Each Gr8r module becomes a React component.
- **Vite** means the Next.js pieces Dotrix relies on must be replaced first: the auth cookie and
  API proxy route handlers, `proxy.ts`, server-rendered redirects, and routing. This is Phase 0,
  and it should land **without visual changes**, so it can be verified on its own.
- About **55% of Gr8r already exists in Dotrix** in some form: Home, My issues, Projects, Tasks,
  Timeline, Activity, Overview, the board, list, and table, the issue drawer, ⌘K, and settings.
  Those need redesign and missing details. About **45% is new**: Calendar, Inbox, Favorites,
  Members and member profiles, Teams, Archive, saved views, a search page, onboarding, task
  attachments, reactions, recurrence, milestones, preferences, and billing.

## 2. Decisions needed before building

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | React on Vite, or Gr8r's vanilla JS architecture? | **React + Vite.** Keep `@pmagent/ui` (shadcn), restyled with Gr8r's tokens. Rewriting the agent surfaces (chat streaming, approvals, diffs, the graph) without React is a far bigger job, for nothing gained. |
| D2 | Router | **TanStack Router** (file-based, type-safe search params). It fits the URL-state convention (`useSearchParam`) and TanStack Query, which is already used. React Router 7 in library mode is the alternative. |
| D3 | Where the session lives without Next's server | **The backend sets httpOnly cookies itself** (cookie mode on `/v1/auth/*`), served from the **same origin** as the SPA: Vite's dev proxy locally, and a reverse proxy (or FastAPI serving `dist/`) in production. This keeps "tokens never reach the browser" without adding a separate server. The alternative is a small Node BFF (Hono), which is one more service to run. |
| D4 | Naming: Gr8r's or Dotrix's? (Tasks vs Issues, My Tasks vs My issues, Inbox) | Gr8r's labels in the UI ("Tasks", "My Tasks"), Dotrix's model in the API (issues with types). Dotrix's copy rule (sentence case) still applies: "My tasks". |
| D5 | Inbox and Notifications: Gr8r has both | **Inbox** for people's items (mentions, assignments, comments on what you watch, with replies inline). **Notifications** for agents' items (approvals, checkpoints, findings, decisions). Both read Dotrix's one notifications table, split by kind. |
| D6 | Statuses: Gr8r `backlog / todo / progress / review / done`; Dotrix `todo / in_progress / blocked / review / done` | Add `backlog` to Dotrix and keep `blocked`. Five-plus-one columns, with Blocked folded by default. |
| D7 | Teams, billing, Google and Microsoft sign-in | Teams yes (small). Billing as UI only, behind a flag, until FR-8. Google sign-in when its OAuth app exists (already a TODO); Microsoft later. |

## 3. Phase 0: Next.js → Vite (no visual change)

What Dotrix's web app uses from Next.js today (counted in `apps/web`):

| Next.js piece | Where | Replacement |
| --- | --- | --- |
| `next/link` (37 files), `next/navigation` (29) | everywhere | Router `Link`, `useNavigate`, `useSearch`, `useParams`. Mechanical, but touches ~66 files. |
| App Router pages (77 route files, `(auth)` and `(app)` groups, layouts) | `app/` | File-based routes under `src/routes/`, with the same URLs (`/w/$workspace/p/$project/board`). Layouts become layout routes. |
| Route handlers (10) | `app/api/auth/{login,signup,logout,magic-link,signup-link,github,github/callback}`, `app/api/github/{install,setup}`, `app/api/v1/[...path]` | **Moved to the backend** (D3): `POST /v1/auth/login` etc. set `pm_access` / `pm_refresh` httpOnly cookies when asked (`?session=cookie`), the API accepts the access cookie as well as a Bearer token, and the GitHub sign-in and app-setup redirects finish on the backend. The `/api/v1` proxy disappears: the SPA calls `/v1/*` on the same origin. |
| Refresh on 401, shared per token (`lib/session.ts`) | proxy | `POST /v1/auth/refresh` with the cookie. **Refresh rotation and reuse detection must survive several tabs refreshing at once**: either keep a short grace window for the just-rotated token on the backend, or a single in-flight refresh per tab plus a `BroadcastChannel` lock across tabs. Today this works because the Next server serialises it. |
| `clientHeaders` (browser User-Agent and address for sessions) | route handlers | Not needed: the browser calls the API directly, so the backend reads them. Keep `PMAGENT_TRUSTED_PROXIES` for the reverse proxy. |
| `proxy.ts` (redirect to `/login?next=` without a cookie) | root | A router `beforeLoad` guard on the `(app)` layout: no session (`GET /v1/me` 401) → `/login?next=…`. |
| Server components that redirect (8 pages: `/agents`, `/audit`, `/p/[KEY]`, `/backlog`, `/docs`, `/chat`, `/briefing`) | `app/(app)` | Router redirects in route definitions. |
| `cookies()` / `headers()` / `server-only` | `lib/session.ts`, route handlers | Gone (backend owns cookies). |
| `next/font/google` | `app/layout.tsx` | `@fontsource-variable/*`, or Gr8r's font stack. |
| `components/after-hydration.tsx` and the hydration rules in CLAUDE.md | project layout | Not needed in an SPA (no server markup to match). Delete it, and the CLAUDE.md section. |
| Streaming (SSE `.../stream`) through the proxy | chat | Same-origin `EventSource` straight to `/v1/...`; check the reverse proxy doesn't buffer (`X-Accel-Buffering: no`). |
| Playwright e2e (`next dev` on :3100) | `apps/web/e2e` | `vite preview` on :3100 behind the same proxy rules; `scripts/e2e_server.py` unchanged. |
| Desktop (Electron loads `PMAGENT_WEB_URL`) | `apps/desktop` | Unchanged if it keeps loading the served app. Loading `dist/` from disk would break same-origin cookies, so don't. |
| Deploy | — | Static `dist/` + rewrites `/v1/*` → API on the same domain (Vercel rewrites, or nginx/Caddy), so cookies stay first-party and `SameSite=Lax` works. |

**Security checks for Phase 0** (CLAUDE.md rules):
- Cookies: `HttpOnly; Secure` (in production); `SameSite=Lax`; `pm_refresh` scoped to `Path=/v1/auth`.
- **CSRF** becomes the backend's job once it accepts cookies. Require a custom header on
  state-changing requests (e.g. `X-Requested-With`, sent by the API client; browsers can't send it
  cross-site without CORS), or use a double-submit token. Keep CORS closed.
- Bearer tokens (CLI, `pmat_…`) keep working unchanged.
- The isolation suite and the auth tests gain cookie-mode cases.

**Done when:** every route renders the same as on Next.js, `pnpm build && pnpm typecheck` pass, the
e2e suite is green, and CLAUDE.md's web section is rewritten for Vite.

## 4. Feature gap: Gr8r → Dotrix

Legend: ✅ in Dotrix, restyle only · 🟡 partly there, needs work · ❌ missing · **BE** needs backend
work.

### 4.1 Shell and navigation

| Gr8r | Dotrix today | Gap |
| --- | --- | --- |
| Sidebar: Home, Inbox (count), My Tasks (count), Favorites, Notifications (count) | Home, Notifications, My issues, Search | ❌ Inbox, ❌ Favorites page (D5) |
| Workspace group: Overview, Projects, Tasks, Calendar, Timeline, Members, Activity | Overview, Chat, Projects, Tasks, Timeline, Activity | ❌ Calendar, ❌ Members page (only in Settings). Keep Chat. |
| Projects: icon and colour per project, status dot, ⋯ menu, drag to reorder, star, lock | key tile, star, lock, chevron | 🟡 **BE** `icon`, `color`, status (§4.10), sidebar order per person; context menu |
| Project sub-items Board / List / Timeline / Files | Overview…Activity (8) | ✅ keep Dotrix's set (adds Knowledge) |
| Archive (count) | — | ❌ **BE** |
| Teams group + New team | — | ❌ **BE** (D7) |
| Help & resources menu, user menu with presence | user menu | 🟡 Help menu |
| Collapse sidebar `[` | rail | ✅ |
| Top bar: breadcrumb, "Search or jump to…", bell with dot, **New ▾** (task, project, invite…), avatar | breadcrumb, New project, search, bell | 🟡 New ▾ menu |
| Mobile bottom nav (Home, My Tasks, Projects, Inbox, More) | sheet sidebar | ❌ |
| Offline bar, skip link, page title + live region, toasts | toasts | 🟡 offline bar, skip link, titles |
| Count-up numbers, route/tab/drawer motion, reduced-motion pref | — | ❌ (`styles/motion.css`) |

### 4.2 Pages

| Gr8r page | Dotrix | Gap |
| --- | --- | --- |
| **Home**: greeting, Invite / New project / New task, 4 stats, My tasks (Upcoming / Overdue / Completed tabs), Project progress table (status, %, due, team avatars), Upcoming deadlines (today, tomorrow, this week), Recent activity | Home: greeting, 4 stats, waiting for a decision, my issues, projects, agent activity | 🟡 tabs, progress table with team, deadlines, quick actions; **keep** "Waiting for a decision" and agent activity |
| **Inbox**: two panes, tabs All / Mentions / Assignments / Comments / Updates, unread toggle, mark all read, reply inline | Notifications page (list and detail, tabs) | 🟡 split (D5); **BE** `comment` kind for watched issues (today `watching`), reply from the preview |
| **My Tasks**: List / Board / Calendar; Upcoming / Overdue / Completed | My issues: List / Board / Table / Timeline; Overdue / Today / Upcoming / No date / Done | 🟡 add Calendar view |
| **Favorites**: projects and tasks | stars (projects only) | ❌ page; **BE** task favourites |
| **Notifications**: filters, unread, preferences link | Notifications | ✅ (agent items, D5) |
| **Search** page: tabs Tasks / Projects / People / Comments, clear | ⌘K palette only | ❌ page; **BE** search comments and people (`GET .../search` covers documents) |
| **Workspace overview**: portfolio, tasks by status, upcoming milestones, workload, completion rate | Overview: counts, portfolio, by status, workload, agents this week | 🟡 milestones (**BE**), completion rate |
| **Projects**: Grid / List / Table, status filter, search, sort, options menu, private lock | Grid / List, search, sort, health, lock | 🟡 Table layout, status filter, options menu |
| **Tasks**: all tasks, toolbar (filter, sort, group) | Tasks by status, search, filters | 🟡 Gr8r's view toolbar (§4.4) |
| **Calendar** (workspace): month / week, tasks + events, day list popover, add task on a day | — (only the iCal feed) | ❌; **BE** events (§4.10) |
| **Timeline** (workspace): zoom, group by, today, milestones | Timeline: weeks / months, by project, dependencies, drag | ✅ restyle; add group by and milestones |
| **Members**: tabs Members / Teams / Roles & permissions; search, role filter, table (role, team, active projects, open tasks, last active, status), ⋯ menu | Settings → Members (search, role chips, projects they see) | 🟡 a top-level page; last active (**BE**), team, counts |
| **Member profile**: stats, assigned / completed, projects, recent activity, Assign task, Copy email | — | ❌ (a page over existing endpoints + **BE** activity by person) |
| **Teams** and **Team** page | — | ❌ **BE** |
| **Activity** | Activity with Everything / Issues / Documents / Agents / Approvals | ✅ restyle |
| **Archive**: archived projects and tasks, restore, delete permanently | — | ❌ **BE** `archived_at` on projects and issues |
| **Settings**: Workspace, Members, Teams, Projects, Permissions; Profile, Preferences, Appearance (theme, accent, density, sidebar, motion), Language, Date & time, Keyboard shortcuts, Password, Sessions; Plan, Payment, Invoices | Profile, Appearance (theme), Notifications, Devices, Calendar, General, Members, Invites, Permissions, Agents, Audit, GitHub | 🟡 Preferences (default home, open tasks in panel / full page, week start, date format, time zone), accent, density, motion, Language, Shortcuts page; ❌ billing (D7). **Keep** Agents, Audit, GitHub, Devices, Calendar feed. |
| **Auth**: welcome back, Google / Microsoft, create account, verify, forgot / reset, password updated | login, signup, magic link, GitHub, verify, forgot / reset, device, invites | 🟡 restyle to Gr8r's split layout; Google (D7) |
| **Onboarding** wizard: workspace → what you work on → how your team works → first project from a template → invite → ready | — (sign-up makes a personal workspace) | ❌; **BE** project templates (seed issues per template) |
| **Errors**: 404, no access (Request access), failed to load, offline | `EmptyState`, not-found | 🟡 Request access (**BE**: request to a restricted project's admins) |
| **Design system** and **System states** pages | — | optional; useful as a dev-only route |

### 4.3 Project page

| Gr8r | Dotrix | Gap |
| --- | --- | --- |
| Header: icon, name, ★, status pill (menu), member avatars, Add member, Share, settings, ⋯ | name, star, Ask in Chat, settings gear | 🟡 status pill, avatars, Share (= project members dialog) |
| Tabs: Overview, Board, List, Table, Calendar, Timeline, Files, Activity + **saved views** + "+" | Overview, Board, List, Table, Timeline, Files, Knowledge, Activity | ❌ Calendar tab, ❌ saved views (**BE**) |
| Overview: About, Progress, Details, **Milestones**, Coming up, Recent activity | about, progress, coming up, epics, details, Ask Chat, activity | 🟡 milestones (**BE**) |
| Files: grid / list, type filter, search, sort, drop zone, preview, rename, duplicate, delete, "uploaded by" | Files: drop zone, type filter, sort, conversion status, retry | 🟡 grid view, preview, rename. Dotrix's files are documents converted for agents; Gr8r's include task attachments (§4.5). |

### 4.4 Views and the filter engine

| Gr8r (`shell/view-engine.js`) | Dotrix | Gap |
| --- | --- | --- |
| One toolbar on every view: search, Filter (fields: status, assignee, priority, due, project, labels, created, updated; **is / is not**; chips with "and"), Sort (11 fields, direction), Group (status, priority, assignee, project, due, none), Columns | filters per page (`components/issues/filters.tsx`), board sort, list group | 🟡 one shared toolbar and filter model; `is not`; created / updated ranges |
| View state remembered per view (`S.views[key]`) | URL search params | Keep the URL as the source; add **saved views** (**BE** `saved_views`: name, type, filters, per project, shared) |
| **Board**: quick add at the top or bottom of a column (inline composer), column ⋯ (add, collapse, sort by priority, mark all done, archive completed), card quick edit, progress on cards, drag between columns | drag, + per column (dialog), keyboard drag, sort | 🟡 inline composer, column menu, collapse |
| **List**: groups, inline add per group, row checkboxes, **bulk bar** (status, assignee, priority, due, move, delete), inline cells (status, priority, assignee, due, labels), subtasks expand under the row | List: ranked / by status, drag rank | 🟡 inline cell editing, bulk bar, expand sub-tasks |
| **Table**: inline edit (double-click title), resizable column widths, columns menu, sort by header | sortable, Columns menu, search, CSV, bulk status / assign | 🟡 inline edit, resize |
| **Calendar**: month / week, drag to reschedule, events, "+N more" day popover | — | ❌ |
| **Timeline**: week / month, group by, today, milestones as diamonds | weeks / months, today, dependencies, drag | 🟡 group by, milestones |
| **Context menus** (right-click) on tasks, projects, members, files, saved views, columns | — | ❌ (shadcn `context-menu`) |
| Drag and drop: tasks between columns and projects, projects in the sidebar, files onto tasks | board columns and rank | 🟡 |

### 4.5 Task drawer (`overlays/drawer.js`)

| Gr8r | Dotrix issue drawer | Gap |
| --- | --- | --- |
| Side panel ↔ **full page** toggle | side drawer | ❌ |
| Mark complete, ★ favourite, copy link, ⋯, close | status, watch | 🟡 favourite (**BE**), copy link |
| Overdue and completed banners (reschedule, reopen) | — | ❌ |
| Properties: status, priority, assignee, due, **start**, project, labels (coloured), **repeat**, estimate, blocked by | status, priority, assignee (person or agent), due, start, type, epic, labels, estimate, dependencies | 🟡 recurrence (**BE**), label colours (**BE** workspace labels), move to another project |
| Description: **rich text** toolbar (bold, italic, lists, heading, link) | Markdown textarea + render | 🟡 a Markdown-producing editor (keep Markdown storage: agents read it) |
| **Subtasks** as a checklist (title, done, due, assignee; open one in place; promote to task) | `sub-task` issues with a parent | 🟡 show sub-task issues as a checklist with inline add; promote = change type |
| **Attachments**: upload with progress, previews, remove, drop zone | — | ❌ **BE** issue attachments (object storage exists: `core/storage.py`) |
| Comments: @mentions, ⌘+Enter, delete own, **emoji reactions**, attach files | comments, @mentions | 🟡 reactions, delete or edit own (**BE**) |
| Activity tab | activity log | ✅ |
| **Keep from Dotrix**: coding sessions and "Start coding", Review, Related (graph), PR link, agent assignees | — | — |

### 4.6 Overlays and keyboard

| Gr8r | Dotrix | Gap |
| --- | --- | --- |
| Modals: new task (chips for every field, subtasks, files, "create more"), new / edit project (icon, colour, template), share, invite, confirm, shortcuts, file preview | new issue dialog, create project page, confirm, shortcuts, invites | 🟡 the task modal's chips, project icon / colour |
| Popovers for every field (status, priority, assignee, date with month picker, labels, deps, estimate, recur, role, project status, workspace, user, help, create, emoji) | dropdowns | 🟡 restyle to Gr8r's popovers |
| Command palette with scopes (tasks, projects, people, actions), run actions | ⌘K: issues, documents, projects, pages, agents, people, Ask the agents | ✅ add scopes and actions |
| Shortcuts (`actions/keyboard.js`): `C` new task, `P` new project, `/` search, `G` then `H/I/M/P/T` go to, `[` sidebar, `J/K` move, `E` edit, `X` select, `Esc`… | some | 🟡 port the map, show it in the Shortcuts page |

### 4.7 Visual design

- Gr8r tokens (`styles/tokens.css`, 207 lines): neutrals, accent (indigo default + choices),
  status and label colours, spacing, radius, type scale (`--fs-*`), `--gutter`, shadows; light and
  dark. Move them into `packages/ui/src/styles/globals.css` as Tailwind 4 `@theme` tokens, keeping
  Dotrix's semantic names (`bg-muted`, `text-muted-foreground`, `bg-brand`) mapped onto Gr8r's values,
  so existing components pick them up.
- Restyle the shadcn components to Gr8r's `components.css` (buttons, inputs, badges, tabs, segmented
  controls, chips, pills, avatars and stacks, progress bars, panels, stats, empty states).
- Gr8r's layout rule: every page edge uses `--gutter`, so breadcrumb, header, toolbar, and content
  line up. Adopt it in the page shell.
- Accent and density preferences (Settings → Appearance) set `data-accent` / `data-density` on
  `<html>`.

### 4.8 What Dotrix keeps (Gr8r has none of it)

Chat (workspace conversations, across projects, coding tab), Knowledge (file tree, history, diffs,
restore, export), documents converted for agents, the agents (contracts, rules, skills, lessons,
automations), approvals and checkpoints with diffs, coding sessions, the project graph and Related,
triage and review, research sources, issue types and epics, restricted projects, workspace switcher
(Personal / Organisation), invites, audit log, GitHub (sign-in, app, repos), devices and tokens,
the calendar feed, notification email settings. In Gr8r's design: Chat and approvals keep their
prominent places (CLAUDE.md UI redesign decisions), and agent items appear in Home, Notifications,
and the drawer.

### 4.9 Data and backend gaps

| Need | Change |
| --- | --- |
| Project icon, colour, status | `projects.icon`, `projects.color`; status: map Gr8r's planning / in progress / at risk / on hold / completed onto `health` + a new `status` (`planning`, `active`, `on_hold`, `completed`), with health kept for on track / at risk / off track |
| Project lead, start date, milestones | `projects.lead_user_id`, `start_date`; `project_milestones` (name, date, done) |
| Backlog status, no priority | `IssueStatus.BACKLOG`; `Priority.NONE` (or nullable priority) + migration |
| Labels with colours | `workspace_labels` (name, colour); issue `labels` stay strings, matched by name |
| Recurrence | `issues.recurrence` (RRULE subset: daily, weekdays, weekly, monthly); next one created when done |
| Attachments | `issue_attachments` (blob key, name, size, type, uploaded by); upload / download / delete; size limits; never for guests |
| Reactions, comment edit / delete | `issue_event_reactions`; edit / delete own comment (logged) |
| Favourites for tasks | `issue_stars` (like `project_stars`) |
| Archive | `archived_at` on projects and issues; lists hide them; restore; permanent delete for owners and admins (audited) |
| Saved views | `saved_views` (project, name, view type, filters JSON, created by, shared) |
| Teams | `teams` (name, icon, colour, description), `team_members`; `projects.team_id` |
| Calendar events | `calendar_events` (project, title, start, end, all-day); also in the iCal feed |
| Members: last active, per-person activity | `users.last_seen_at` (updated at most every few minutes); activity filtered by person |
| Search: people and comments | extend `GET /v1/workspaces/{id}/search` with `source=people|comments` |
| Onboarding and templates | project templates (seed issues and documents per template), "what you work on" stored on the user |
| Preferences | `users.preferences` JSONB (default home, open tasks in, week start, date format, time zone, language, density, accent, motion) |
| Request access | notification kind `access_request` to a restricted project's owners and admins |
| Billing (later, FR-8) | none now; UI behind a flag |

Each new table follows CLAUDE.md: `workspace_id`, a migration, router → service, a test per
endpoint, a row in the isolation suite's `World`, permissions on the route, `pnpm openapi`.

## 5. Phased plan (one PR each, each usable on its own)

| Phase | Scope | Backend |
| --- | --- | --- |
| **0. Vite** | §3: router, cookie auth on the backend, same-origin `/v1`, guards, redirects, e2e on Vite, CLAUDE.md | cookie mode, CSRF header, refresh grace |
| **1. Design system + shell** | Gr8r tokens into `packages/ui`, restyled components, sidebar (groups, counts, project icons and status dots, Help), top bar with New ▾, bottom nav on phones, motion, skip link, page titles | project `icon`, `color`, `status` |
| **2. Home, My Tasks, Inbox, Favorites** | Home as Gr8r's (keeping agent cards), My Tasks + Calendar view, Inbox / Notifications split, Favorites | backlog status, issue stars, comment notifications |
| **3. Views** | shared view toolbar and filter model, saved views, board composer and column menu, list inline edit and bulk bar, table inline edit and resize, context menus, project and workspace Calendar | saved views, events, workspace labels, `Priority.NONE` |
| **4. Task drawer** | full page mode, banners, rich Markdown editor, sub-tasks checklist, attachments, reactions, recurrence, copy link | attachments, reactions, comment edit / delete, recurrence |
| **5. People** | Members page, member profiles, Teams and Team pages | teams, `last_seen_at`, activity by person |
| **6. Projects** | header (status pill, avatars, Share), milestones on Overview and Timeline, Projects Table layout and status filter, Archive | milestones, lead, start, archive |
| **7. Settings, auth, onboarding** | Preferences, Language, Date & time, Shortcuts, accent / density, Gr8r auth screens, onboarding wizard with templates, search page, error states, Request access | preferences, templates, search people / comments, access requests |

Rough size: Phase 0 is 1-2 weeks; Phases 1-7 are ~1 week each with backend work, ~8-10 weeks in all.

## 6. Risks

- **Auth regressions in Phase 0.** Keep the e2e auth tests and the isolation suite green, add
  cookie and CSRF tests, and test several tabs refreshing at once.
- **Losing the agent surfaces' prominence** in Gr8r's calmer layout. Chat, approvals, and agent
  activity keep the places the UI redesign gave them.
- **Markdown vs rich text.** Agents read and write descriptions as Markdown; the editor must
  produce Markdown, not HTML.
- **Scope creep.** Gr8r's settings include billing and languages that have no backend. Ship them
  behind a flag or leave them out until they do.
