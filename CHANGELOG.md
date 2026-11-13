# Changelog

Every notable change to dotrix, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [Semantic Versioning](https://semver.org/): before 1.0, a minor version can change the API or the database.

Add each change under **Unreleased** in the PR that makes it (Added, Changed, Fixed, Removed, Security). A release turns
Unreleased into a version (`python scripts/release.py bump X.Y.Z` on `stage`); merging `stage` into `main` tags it and
publishes the GitHub release. See [Branches and releases](CLAUDE.md#branches-and-releases).

## [Unreleased]

### Added

- dotrix chat: /plans lists the conversation's saved plans, and /build [version] builds the one you pick.
- dotrix code --plan-only and dotrix codes follow --plan-only ask Kai for a plan first; --plan TURN builds from that plan.
- dotrix codes show prints a Plan turn's plan and a turn's parallel tasks; --details adds its skills and unavailable capabilities.

### Changed

- Consolidated product, release-readiness and agent design documentation into two current guides, replacing obsolete proposals and updating navigation.
- Kai's coding engines are updated: Claude Code 2.1.323, Codex 0.169.0, OpenCode 2.3.0, and the browser's Playwright MCP 0.0.85.

### Fixed

- When the platform refuses an agent's tool call (Plan mode allowing only read-only specialist tasks, wrong arguments, a permission it doesn't have), the agent is told why and carries on, instead of seeing "Tool failed." on fx or ending the whole run on DeepAgents.
- Stopping a coding turn now also ends what Kai started during it, such as a test run or dev server, instead of leaving those processes running in the sandbox.
- dotrix runner (and the desktop app's local coding) keeps waiting through a brief network or server outage instead of exiting.
- Kai's session now says when a tool call wasn't allowed ("Not allowed to run …") instead of the call disappearing, without showing the coding engine's own refusal text; its own checklist updates are no longer listed as steps.
- Agents see your project.md and current-state.md as written, up to 1,500 characters, instead of a single line cut at 200.

### Security

- Local coding (dotrix runner and the desktop app) no longer runs a repository's own Claude Code hooks, permission rules, plugins or MCP servers. Without Docker Sandboxes, Claude Code there gets only its file tools (no shell commands) and none of the repository's CLAUDE.md or skills.
- A cloud coding turn whose changes or summary contain your model key, as written or base64-encoded, is refused before anything is committed or pushed.

### Security

- Kai on Codex no longer takes a repository's AGENTS.md as instructions, and no longer applies a repository's own Codex settings (.codex/config.toml).

## [0.2.0] - 2026-11-12

### Added

- A Getting started guide for the beta on dotrix.cc, linked from the app's Help & resources: connecting your key and GitHub, approvals, stopping a run, and reporting a problem.
- `deploy/migrate.sh` shows a deployment's database migrations, backs the database up, applies what's waiting and checks the result; the deploy guide has a checklist for the first deploy, every release and this one.
- Operators can be emailed when dotrix needs attention (a service down, no worker, stuck or failing runs) and again when it clears; the admin console's Overview lists what is open.
- The admin console keeps a record of admin sign-ins and changes to admin accounts, shown to owners.
- The admin console's audit log can be filtered by workspace, by who acted and by date.
- The admin console has a Models page (runs, failures, limit stops, tokens and estimated cost per model and provider), and its cost figures include chat.
- The admin console supports several admins: an owner invites others by email, each sets their own password, owners and viewers have different rights, and an owner can disable or remove an admin.
- Operators can list admin console accounts, create one and reset one's password from the server's command line (python -m dotrix_backend.admin_cli).
- The admin console's health now covers Redis, workers, file storage, email, the GitHub App, waiting emails and automation events, and coding capacity.
- Each workspace has a storage limit for uploaded documents and task attachments (1 GB by default; the operator can change it per workspace). Settings shows how much is used, and an upload that doesn't fit is refused with the reason.
- NVIDIA as a model provider: connect your build.nvidia.com key (`nvapi-…`) in Account → Your models to use NVIDIA's hosted models, which are free to try with rate limits, for chat and for Kai (on OpenCode or fx). Six are offered, each checked live for fast, working tool calls: Nemotron 3 Ultra, Nemotron 3.5 Lightning, Nemotron 3.5 Bolt, Mistral Large 4, Gemma 4 31B and Laguna XS 2.1.
- A private solo beta readiness page (`docs/product.md`): the supported configuration, the checks to run where, and the known limitations to tell participants.
- Personal workspaces can launch on their own: with `DOTRIX_ORGANISATIONS` off (the default on staging and production), organisation workspaces can't be created, joined, opened or moved into, and the app hides every way to reach one. A personal workspace also no longer shows Members, Permissions or invites. Existing organisations keep their data and return when the setting is turned on.
- Optional first-workspace choice after signup, defaulting to Personal, with durable organisation setup and a labelled onboarding stepper.
- Project readiness across setup, Overview and empty task views, with private model evidence and next actions that explain missing prerequisites and permissions.
- Preview and import selected GitHub Issues into project tasks with explicit state/label/assignee mappings, shared visibility confirmation and source links. Retries skip imported work and preserve human edits; later GitHub changes are not automatically synchronized.
- Published chat outcomes can link shared documents and tasks, and explicitly supersede a reviewed decision. Changed document versions require renewed review; replacement links preserve the original text and history, and Knowledge shows shared relationships.
- Explicit publication of edited private-chat outcomes as new requirements, decisions, research documents or unassigned tasks. Preview content and project visibility before confirming; retries are duplicate-safe, existing knowledge is preserved, and private conversations remain private.
- Shared tasks show published PR, commit, current-check and GitHub review evidence while coding conversations stay private. PR merge state remains separate from task completion. Pending review-posting claims are never shown as published review links.
- Existing repositories have a guided baseline review: inspect coverage and citations, add shared goals or corrections, and confirm an exact evidence revision before opening a planning draft. Changed evidence makes the review out of date; retries retain drafts and avoid duplicate review records.
- New-project setup checks GitHub for a committed default branch and offers an editable first-implementation plan. Kai refuses new sessions on empty or inaccessible repositories and keeps the validated base branch while awaiting approval.
- Shared project setup can create an organisation repository after owner/name/visibility confirmation, recover uncertain responses through repository selection, and guide personal accounts through creation on GitHub. Repository creation rechecks installation ownership and suspension.
- Project setup offers Explore an idea, Start a new codebase and Connect an existing repository, with saved starting choices, goal-first planning and editable Nova discussion starters. Existing projects can connect a repository from Overview.
- New-account setup saves a first project, offers GitHub repository access and personal model setup, and resumes after GitHub installation.
- Self-hosting: the admin console is part of the production deploy (`admin`, on its own domain such as admin.dotrix.cc),
  and `pnpm docker:up` also runs the public site (http://localhost:3200) beside the web app and the admin console.
- Local coding in a Docker sandbox: with Docker Sandboxes (`sbx`) installed, each turn on your computer runs in a microVM
  of its own with only its worktree, so Kai can run tests and commands there; its key comes from your own
  `sbx secret set`. Without `sbx`, local turns still only edit files. `dotrix runner --isolation auto|sbx|none`.
- Kai's turns can run in Docker Cloud sandboxes (`DOTRIX_CODING_SANDBOX=docker-cloud`): a microVM per session, reaching
  only the model API, with the model key kept out of the sandbox as a Docker secret. The coding image is published to a
  registry for each release.
- A session's Docker Cloud sandbox sleeps between turns (stopped, its files and installed dependencies kept) and wakes for
  the next one. It's deleted after 7 days asleep, or straight away when the session is closed or deleted or someone
  deletes it ("Delete sandbox" in the session's menu: whoever started it, or owners and admins); at most 5 sleep per
  workspace.
- Settings → Network: owners and admins choose package registries and other hosts Kai's sandboxes may reach,
  for every project or one; every change is audited, and a turn says which hosts its sandbox blocked.
- A Windows installer for the desktop app and a standalone Windows CLI, built and attached to each release (unsigned for
  now).
- dotrix.cc, the public site (`apps/site`): what dotrix does, with screenshots, and links to sign in to the web app at
  app.dotrix.cc and to download the desktop app and the CLI. Deployed beside the app as the `site` service.
- The admin console (`apps/admin`, formerly Ops) watches the whole platform: health (database, run queue, workers,
  stuck runs, recovery, runners and sandboxes), runs and failures per day, failures grouped by error, coding by engine
  (outcomes, PRs, time to finish, cost), workspaces by use, and the audit log, in tables with pages (rows per page,
  page numbers) and shadcn charts. Redesigned on dotrix's own design, sign-in included, which loads before the rest.
- `dotrix chat` matches the app: pick the work mode (`--mode`, `/mode`: Discuss, Plan, Build, Review), the approval mode
  (`--approvals`, `/approvals`) and, for a new conversation, the runtime (`--runtime fx`); see Nova's thinking as it
  comes; stop a reply with Ctrl+C; `/continue` after a model's limit (now, or `/continue later` once it resets); in Build,
  the session Kai starts is named.
- `dotrix codes` in the terminal: list Kai's sessions, show one (each turn's request, steps, summary, files, the pull
  request and its checks, `--diff`), follow up, approve or reject a turn, accept or discard its changes, stop, revert,
  recover, and wait for a turn. `dotrix code KEY` takes `--approvals`, `--model` and `--wait`.
- The desktop app updates itself: it downloads a new version in the background, says when it's ready (Restart, or it
  installs when you quit), and shows What's new after an update and from the sidebar.
- Codes: a new session's "where it codes" menu lists this computer's folder for the project, the cloud sandbox, and, in
  the desktop app, Add a folder; each session in the list shows whether it codes in the cloud or on a computer.

### Changed

- Skills can declare pinned reference resources and required tools; Codes shows skill versions, available capabilities and missing dependencies.
- Cloud coding turns and background workers receive skill descriptions and read pinned skill files on demand instead of receiving every procedure in their prompts. Local runners retain inline skills.
- Codes shows expandable background tasks for every turn, including saved activity, command output, verification results and live status.
- Codes supports private Plan turns and an explicit Build action; read-only planning refuses hosts that cannot enforce its filesystem boundary.
- Coding can execute independent plan tasks in separate sandboxes behind `DOTRIX_CODING_PARALLEL`, with scope checks, saved task results, combined verification and one existing approval/publication flow.
- Agent runs pin versioned skill catalogs; specialists inherit their parent catalog and Kai's workers receive its saved instructions.
- Saved plans can include repository revisions, task ownership, implementation instructions, checks and stop conditions, shown in the plan card. Incomplete or cyclic execution specifications are rejected.
- Agents have shared procedures for writing and reviewing executable plans, including dependencies, ownership, evidence and verification.
- Approve and Reject work in place in the agents panel and the corner notices for everything that waits on you: Kai's turns waiting to start or with checked changes to push, and all of an agent's waiting changes, not only a single board change. A plan to steer still opens, since it needs your choice.
- Saving a setting (your models and keys, the workspace's permissions and approval limits, an agent, a repository) refreshes only what it affects. Before, it reloaded the whole workspace.
- Every change you make to tasks, comments, projects, members, notifications, documents, files and automations shows everywhere at once and refreshes only what it affects. If it can't be saved, it's undone with the reason, without reloading the rest of the workspace.
- People, projects, notifications, activity, files, documents and automations show a change the moment it arrives, everywhere in the app, instead of a moment later on some screens.
- Menus, list rows and drag and drop read a task from the same data as the board, with no copy in between, so a change shows everywhere in the same moment.
- The task panel reads a task from the same data as the board and the lists, so an edit made in one shows in the others at once.
- Editing, moving, commenting on or adding a task refreshes only what tasks appear in (task lists, activity, notifications, search) instead of reloading the whole workspace, so the app does less after every change.
- A new task shows on the board and in the project's list the moment you add it, before the server has answered; if it can't be saved, it's taken away again with the reason.
- Codes follows Kai as it works: an open session's steps, command output, status and changes arrive over a live stream instead of a check every few seconds, so a turn no longer looks slower than it is. If the stream can't be kept open, Codes goes back to checking.
- Help & resources has "Report a problem", which opens a new issue on dotrix's GitHub repository.
- In a personal workspace a project shows no members, Add member, Share or Lead (in its header, Overview, the Projects list and its settings): there's only you.
- Help & resources shows "Reset demo data" and "Simulate offline" only in the sample workspace, not in your own.
- In a personal workspace every task is yours: My Tasks becomes Tasks and lists unassigned tasks too, and Home shows your open tasks due this week instead of who they're assigned to, with no Team column.
- Chat lays out a conversation as Codes does: your message in a bubble on the right, the agent's reply under its face and name, both edges in line with the message box.
- Codes' Files reads as Claude Code's file view: a file's content highlighted in light and dark with line numbers, its path as a breadcrumb with its icon, whether the turn changed it and Copy path; the tree shows file-type icons and colours changed files. Diffs stay in Changes, now highlighted too.
- Chat and Codes show an agent's work the way shadcn/ui's AI Elements do: Nova's thinking as a Reasoning line that's open while it thinks, a reply's steps as a Chain of Thought, each specialist as a Subagent line with its brief, findings, risks and evidence, and Kai's tool calls as lines whose commands open onto their output (a failed one in red, the current one shimmering). Model menus group models by provider, and Files opens folders as a file tree.
- A reply's sources show as inline citations ("[S1]" names the site; hover for the page) and a "Used N sources" list; each reply shows its tokens, broken down on hover. Plans show their tasks, criteria and questions as steps; messages queued or steering a turn show as a queue with Cancel; a change waiting for approval asks as one row with Reject and Approve. In Codes, a command's output is read for its test results (counts and the failing tests) and stack traces (your own frames linked to Files, library frames folded), in the turn and in Terminal, and each pushed turn ends with a checkpoint naming its commit, with Revert there.
- Chat and Codes list conversations and sessions in one list, each naming its project; the work mode is picked from the composer's + menu; a new coding session picks its approvals; the project list in a new chat stays in the window and scrolls.
- New project uses the same resumable setup as signup, with confirmed saves, optional description/access and recovery after a lost team or project save response. Invitees join their workspace/project first; email links preserve local return destinations.
- Document the accepted solo/team project journeys and ordered delivery checklist: idea exploration, new codebases, existing GitHub projects, shared outcomes, backlog import and readiness.
- The READMEs are up to date: the fixed team and personal model keys, Codes and Juno's reviews, the desktop app,
  `dotrix codes` and local turns in Docker Sandboxes, the admin console and site, and how to deploy.
- New chats and Codes sessions look like Claude Code's: a card in the middle to choose the project (or where Kai codes:
  this computer's folder or the cloud), and a rounded message box at the bottom with + on the left and send on the
  right; the mode, approvals and model sit under it as plain text. Model names are short ("Opus 5.5", "GPT-5.5"), and
  the "Coding is off" chip, the keyboard hints and the explainers are gone. Enter starts a session.
- Self-hosting: file storage is RustFS (`rustfs/rustfs:1.0.3`, S3-compatible) in place of MinIO, whose images left Docker
  Hub. The service is `storage` with a fresh `storagedata` volume; `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` keep
  their names. Copy any existing MinIO files across before switching (e.g. with an S3 client's sync).
- Codes looks and works like Claude Code's session view: a details column (where Kai works, the repository and
  branch, usage, the files it changed, the pull request and its checks); several panes open at once, stacked
  (Changes, Files, Terminal, Review), each expandable, from the session bar or its "…" menu; each turn's steps folded
  into one line; and a rounded message box with the model and approval mode under it. Changes marks files as viewed.
- Icons are Phosphor everywhere, and page titles use Geist Serif.

### Fixed

- Join the planning and delivery migration histories so database upgrades and test setup work after their stage merge.
- Building a saved plan pins its version and includes its tasks and acceptance criteria in Kai's approval brief.
- Kai receives custom skills intended for every agent as well as coding-specific skills.
- Plan mode restricts agents to read-only project work and saved plans, rejects mutating specialist delegation, and detects cyclic plan dependencies.
- A restart while notification emails are going out no longer sends the same emails again.
- A long reply on the fx runtime no longer fails with "the runtime journal has reached its size limit": steps a checkpoint has replaced are cleared.
- Juno's review of a pull request is posted on a later attempt when an earlier one failed or was interrupted; before, it could be skipped for good.
- A coding session's sandbox is shut down when it can't be checked for reuse, and the turn starts in a fresh one.
- A push or a failed CI run reported by GitHub while the job queue is briefly unavailable is still followed up (the checkout synced, Juno asked to look); before, it could be skipped.
- A workspace or project with more than 5,000 tasks now shows all of them.
- The README's CLI install instructions now describe installs that work (the release download, or a checkout).
- Kai's changes to files that aren't UTF-8 text (older encodings such as Latin-1) are now pushed exactly as written, from cloud and local turns; before, cloud turns replaced those characters and local turns refused them.
- A turn coded on your computer now delivers every step to the session, including the last ones, and a turn that changed a file that isn't UTF-8 text now fails with a clear reason instead of sending damaged changes.
- A new reply in Chat no longer opens showing the previous reply's text, and a reply in a conversation across projects keeps streaming after a dropped connection.
- A task list grouped by assignee now shows tasks assigned to an agent (such as one Kai is coding) and to people who have left; grouped by due date it keeps finished tasks whose date has passed; estimates sort as numbers; and lists show comment counts in every workspace.
- Clicking into a task's description and out again no longer saves it when nothing changed, and the description editor keeps links, headings, italics and nested lists.
- Clicking into a task's description and out again no longer saves it when nothing changed, and the description editor keeps links, headings, italics and nested lists. A description with a table or code block opens read-only instead of being flattened.
- Making several changes in quick succession (dragging cards, ticking subtasks) no longer makes one of them jump back for a moment, and a change that can't be saved no longer undoes the others on screen.
- After you approve an agent's change in Chat or a coding turn in Codes, the board, the lists and the open task show the new status and assignee at once.
- Dependency versions are now read correctly from requirements files with hashes (pip-compile), so known vulnerabilities in them are found; and a dependency file with an unexpected format is listed as unread and no longer breaks a project's dependencies view.
- A brief loss of connection (waking a laptop, a server restart) no longer replaces the workspace with an error screen or sends you to sign in again.
- Renaming, moving, starring, commenting on or deleting a task in the moment after you add it is no longer lost.
- Asking Kai to start on the same task twice at the same moment (a double click, two tabs) now gives one coding turn, not two.
- A follow-up you queued while an agent was answering now survives a worker restart and stops when you press Stop, like any other message.
- A reply cut off by a worker restart and retried no longer repeats a change that had already gone through: the retried step asks for approval first, as a recovered run does.
- A coding turn that was queued more than once (accepting its changes, a recovery retry) is no longer marked as needing recovery while it is still working.
- Approve on a coding session waiting in the agents panel or a corner notice no longer looks approved without starting it: it approves the turn on the server.
- A project conversation on an xAI, DeepSeek, Mistral, Groq or OpenRouter model no longer fails before it starts. Those providers have no built-in web search, and the run refused to start without one.
- Changing the status, priority or assignee of several selected tasks at once in List is saved. Before, it showed the change but didn't keep it after a reload.
- A card dragged to a new place in its board column, or a row dragged in a project's list, keeps that place. The board showed a project's tasks by due date, so a card went back to where it was.
- A project's board and list no longer say "No tasks here" for a moment while its tasks are still loading.
- A notice about a run that stopped no longer has a red stripe down its left edge; its face and Continue button say what it is.
- On tablets the agents panel and corner notices stay cards at the bottom right instead of stretching across the window; phones keep the full-width banners.
- The web app opens a workspace even when the API is older than it and has no `/v1/features` yet; it then offers no organisations.
- A reply that fails (a provider out of credits, a refused request) says so in Chat: "Nova didn't finish" with the provider's message as plain text, instead of showing that message as if the agent had written it.
- Your computer's runner no longer removes an old worktree you've edited: a file changed in it in the last few days now counts, not only the folder itself.
- A command in a Docker Cloud sandbox that prints without newlines can no longer fill the worker's memory: a line is cut at 4 MB and the rest dropped up to its newline, as in the Docker sandbox.
- A message sent the moment Nova's reply appears is sent, instead of being refused as a follow-up to a turn that had just finished.
- Baseline confirmations include the shared human-context revision. An intervening correction rejects stale confirmations, and confirming without new notes preserves the context instead of erasing it from Nova’s summary.
- Repository discovery writes only wiki pages; selected-page refreshes retain their allowed paths across approvals and recovery, preserving human requirements, decisions and unselected pages.
- Coding outcomes return to Nova on the original chat runtime, so an fx conversation stays on fx after Kai and Juno finish.
- Sample coding-session menus keep management actions read-only and never invoke live mutation hooks, including when a signed-in person opens the demo.
- Seeded Chat/Codes and Rules/GitHub Settings share live presentation; restore Geist Sans/Mono headings and keep workspace navigation available before model setup.
- A local turn's worktree is removed once it has been untouched for 3 days, so they no longer pile up on your
  computer; an open file from a local turn stops refreshing once the turn is done.

### Removed

- Personal-to-organisation workspace conversion; create separate organisations and move selected projects explicitly.
- The fx chat runtime comparison (`experiments/fx-chat`) is gone: fx has been a normal choice for a conversation since
  2026-10-30, not an experiment. Developers only; nothing changes for people using dotrix.

### Security

- Admin console sign-in needs a code from an authenticator app, with recovery codes for a lost device.
- The admin console's failure report shows a kind of failure (for example "HTTP 429" or "timed out") in place of the raw error text, which could repeat part of what someone asked.
- Updated a routing dependency for two moderate advisories.
- If an account's email was never verified, signing in to it with GitHub or an emailed link (or resetting its password) now removes the password set before that and signs out every browser, app and API token, so nobody who registered the address earlier keeps access. Verified accounts are unchanged.
- The app and the admin console can no longer be shown inside another website's frame, and they send stricter content-type and referrer headers.
- Creating the admin console's first account now needs the deployment's setup token (DOTRIX_ADMIN_BOOTSTRAP_TOKEN); without it, admin sign-up stays closed on a deployed server.
- Text that reaches Kai's brief or Juno's look at a failed build (issue text, imported GitHub issues, documents, CI logs) can no longer break out of the part of the prompt marked as data.
- CI's build steps are pinned to exact versions and run with the least access they need.
- Staging and production Docker coding require gVisor and a finite worker run limit. Both coding and egress containers verify their configured runtime before repository upload, with no fallback; swap is disabled and egress CPU is capped.
- A computer coding a turn locally can only report a full commit ID as the turn's starting point; anything else is refused.
- The desktop app opens only web and email links in your browser, and its window stays on dotrix (and GitHub's sign-in pages).
- The admin console no longer sees what people wrote: runs are named by workspace, project and issue instead of a
  conversation's title or first message, and audit events come without their details.

## [0.1.0] - 2026-10-31

The first versioned release: everything built before versioning began, through #199.

### Accounts and workspaces

- Sign-in by email and password, magic links, and GitHub. Email verification, password reset, sessions (browsers and the
  desktop app), personal API tokens, profile and photo, notification settings, rate limits, and email through Sendly.
- Personal and organisation workspaces: roles and a permission matrix with member grants, invites by email and link,
  teams, restricted projects, moving projects, turning a personal workspace into an organisation, and an audit log.
- Personal model keys (BYOK): every run uses only the requester's own encrypted key, never a workspace's or the
  server's. Each person has a default model, a model per agent, and their own instructions for each agent.

### Projects and the board

- Issues with keys, types, checklists, repeats, stars, attachments, dependencies, claim, archive, delete, and moves
  between projects. Comments with edits, reactions and @mentions, plus watchers.
- Knowledge files with version history, document uploads converted to Markdown, a project activity feed, and
  notifications in the app and by email (as they happen, or as a daily digest).
- The project graph (nodes and links from issues and documents; impact, paths, stale documents), and hybrid search
  (pgvector and full text).

### Agents and Chat

- A fixed team: Nova leads Chat with Lyra, Orion, Vega, Juno and Echo. Nova delegates to durable specialist tasks with
  their own checkpoints, the requester's permissions and keys, and serialized project-changing work.
- Work modes (Discuss, Plan, Build, Review) and approval modes (Manual, Accept edits, Auto). Every change is approved
  and audited, standing rules can let an agent act without asking, and the workspace caps the mode.
- Two chat runtimes: DeepAgents (the default) and fx, chosen per conversation. Both have the same approvals, and every
  fx turn is journaled and recoverable.
- Durable runs: leases and fencing, recovery from the last checkpoint, persisted run events that a stream can resume
  from, and Continue after a model limit.
- Steering and queued follow-ups for an active turn, pipelines with checkpoints and structured results, context packs,
  rules, skills, lessons from rejections, web research with checked claims, and automations on schedules and events.
- Nova decides before reading anything whether a message needs the project, shows its thinking, and describes what it's
  doing in plain words.
- Engineering skills scoped to each agent (threat modelling, security review, API and schema design, backend and
  frontend review, acceptance criteria, library evaluation, runbooks), and a definition of done for Kai and Juno.

### Coding with Kai

- Kai codes issues in sessions, on Claude Code, Codex, OpenCode or fx underneath; a session picks its model, the engine
  follows it, and the engine is never shown.
- Cloud turns run in a Docker sandbox whose only way out is an egress proxy to the model API (OpenShell is also
  supported). Local turns run on a person's own computer through `dotrix runner` or the desktop app.
- One commit per turn on the session's branch, pushed without force; the first pushed turn opens the PR. Manual mode
  waits on an approver before starting and again before pushing; changes to files CI runs always wait for a person.
  A pushed turn can be reverted.
- Leases, fencing, and recovery from what GitHub shows when a worker stops mid-turn.
- Codes, a page of its own below Chat, with a side panel per turn: Changes (diffs with Juno's findings on their lines),
  Files, Terminal and Review.
- Juno on GitHub: its review posted on Kai's PR (a comment, never an approval), its look at a failed CI posted there
  with "Ask Kai to fix", and any finding opened as a GitHub issue when a person asks.

### Repository knowledge

- An inventory of every tracked path at each sync, with coverage of the 12 knowledge domains. "Explain the repository"
  has Echo write a cited wiki, pages go stale when their sources change (with a notification), and the pages reach every
  run's context and Kai's brief.
- Dependencies read from manifests and lockfiles (npm, pnpm, yarn, Python, Cargo, Go), and known vulnerabilities in
  them from OSV.dev (`dependency_advisories`).

### Apps and deployment

- The web app (Vite, React, TanStack Router) on seeded data at `/w/dotrix`, and on a real workspace through the API.
- The `dotrix` CLI (device login, linked checkouts, chat, the board, `dotrix runner`) and its MCP server for Claude
  Code and Codex.
- The desktop app (Electron), which bundles the CLI's runner for local coding.
- The ops admin app with workspace observability.
- Production on one VPS with Dokploy (`deploy/README.md`), including the hosts the API and worker need to reach.

### Releases

- Versioned releases: this changelog, one version for every package (`scripts/release.py`), a `stage` branch every PR
  goes into, and a GitHub release tagged `vX.Y.Z` when `stage` merges into `main`.

[Unreleased]: https://github.com/adeyemiadekunle/dotrix/compare/v0.2.0...stage
[0.2.0]: https://github.com/adeyemiadekunle/dotrix/releases/tag/v0.2.0
[0.1.0]: https://github.com/adeyemiadekunle/dotrix/releases/tag/v0.1.0
