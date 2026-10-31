# Changelog

Every notable change to dotrix, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [Semantic Versioning](https://semver.org/): before 1.0, a minor version can change the API or the database.

Add each change under **Unreleased** in the PR that makes it (Added, Changed, Fixed, Removed, Security). A release turns
Unreleased into a version (`python scripts/release.py bump X.Y.Z` on `stage`); merging `stage` into `main` tags it and
publishes the GitHub release. See [Branches and releases](CLAUDE.md#branches-and-releases).

## [Unreleased]

### Added

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

### Changed

- Icons are Phosphor everywhere, and page titles use Geist Serif.

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

[Unreleased]: https://github.com/adeyemiadekunle/dotrix/compare/v0.1.0...stage
[0.1.0]: https://github.com/adeyemiadekunle/dotrix/releases/tag/v0.1.0
