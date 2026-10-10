# Coding agent: design

Status: proposed, 2026-10-10; revised the same day with the owner's decisions (approval modes,
session visibility) and a review against the code. Builds on the coding runs in
`apps/backend/src/dotrix_backend/modules/coding/` and replaces their one-shot model with a session per
issue. The plan and checklist are in [CLAUDE.md](../CLAUDE.md) under "Plan: coding agent". Claude Code
facts below come from the headless and sessions pages at code.claude.com/docs/en; anything marked
**unverified** must be checked (Phase 0) before it is built on.

## Goal

A person assigns an issue, or starts a session about it, and a coding agent (Claude Code, or Codex)
works on it in its own sandbox. The person can follow the work live: what the agent says and does, the
terminal, the file tree, the diff, and a running app in a browser. They can continue the session with
follow-up turns. Every change is in git, and each session's **approval mode** decides where a person
steps in: before a turn starts, before its changes leave the sandbox, or only at the PR.

## Invariants

These hold whatever the implementation does, and whatever the approval mode.

1. **The sandbox is the blast radius.** The agent gets the repo, its tools, and the model API (plus
   package registries and the preview port, Phase D). Nothing else.
2. **No GitHub token ever enters a sandbox.** The worker fetches and pushes with installation tokens,
   outside it.
3. **Git is the record.** Every turn that changes something ends in one commit on the session branch.
   The history of the session is the history of the branch.
4. **People merge.** No mode pushes to the default branch, merges, or deploys (FR-26). The guard
   (`guard.py`) checks every turn's changes in every mode: nothing under `.dotrix/`,
   `.github/workflows/`, or `.git`, and size limits.
5. **A session's approval mode never exceeds what the person who set it may do**, and never exceeds
   what the workspace's owners allow (below).
6. **Repo content is data.** Code, docs, `CLAUDE.md`, and `AGENTS.md` from a repo never change the
   platform's rules. The agent's instructions come from the platform; the repo's come only as
   conventions to read.
7. **The platform's own settings, hooks, and MCP servers are the only ones that run** in a sandbox.
   A repo's `.claude/` and `.mcp.json` are never loaded.
8. **Every action is audited**, every route is covered by the isolation suite, and nothing (branch,
   transcript, key) crosses workspaces.

## Approval modes

Each session has a mode, like Claude Code's permission modes, picked when it starts and changeable
while it runs (by whoever started it, within the limits). The mode decides two gates: **start** (a
turn may run, and spend tokens) and **accept** (a turn's commit may leave the sandbox and be pushed).

| Mode | Turn starts | Turn's commit is pushed | Who may pick it |
|---|---|---|---|
| **Manual** (default) | after an approver approves it | after an approver accepts its diff | anyone who may instruct the coding agent (`agents:code`) |
| **Accept edits** | the first turn after an approval; follow-ups at once | at once, after the guard | people who may also approve agent changes (`agents:approve`) |
| **Auto** | at once | at once, after the guard | the same, and only where an owner has turned Auto on |

- **Workspace limit.** Owners set the highest mode the workspace allows (Settings → Agents → Coding):
  Manual only (the default), up to Accept edits, or up to Auto. Changing it is audited; lowering it
  moves running sessions down to the new limit.
- **The person's limit.** Someone who may instruct but not approve gets Manual only, whatever the
  workspace allows. A session's mode is recorded on each turn (`approval_mode`), so the audit log says
  under which mode a commit was pushed and who set it (`coding.mode_changed`).
- **What every mode keeps:** budgets (tokens, time, warm sandboxes), Stop, the guard, the sandbox's
  limits, and the PR as the review point. Accept edits and Auto remove clicks, not checks.
- **Rejecting after the fact.** In Accept edits and Auto, an approver can still reject a pushed turn:
  the platform pushes a revert commit (never a force push) and the agent is told why on its next turn.
- **Claude Code's own permission mode** inside the sandbox is separate and stays fixed:
  `--permission-mode dontAsk` with a platform `--allowedTools` list and `--permission-prompts none`.
  The sandbox, not a prompt, is what limits the agent's commands; denials become events.
- **Automations and assignment.** A session started by assigning an issue to a coding tool, or by an
  automation, starts in Manual unless the person who set it up may pick a higher mode and did.

## Visibility

Sessions follow the same rule as conversations (`agents/privacy.py`, decided 2026-10-09):

- A session is visible only to **whoever started it**, in personal workspaces and organisations alike.
- An **approver** can open a session while one of its turns waits on their decision (Manual's start or
  accept), so they see what they're deciding, and lose it once decided.
- An **automation's** sessions belong to the workspace: owners and admins see them too.
- What the agent changed stays **public** to everyone who sees the project: the branch, the PR, the
  issue's log ("Pushed turn 2 to PR #7"), and the audit log. Transcripts, events, the terminal, and the
  preview are the session's, and private like a conversation.

## What we build on (Claude Code)

- **Headless turns.** `claude -p --resume <session_id> --output-format stream-json --verbose
  --include-partial-messages`, the request on stdin, runs one turn and streams its events. The final
  `result` carries `total_cost_usd` and usage.
- **Session state is the transcript.** Claude Code keeps each session as a transcript file under its
  home folder, keyed by the working directory. The repo is always at `/sandbox/repo`, in every sandbox
  and both backends, so a restored transcript is found where `--resume` looks (**unverified** with
  `--bare`; Phase 0).
- **Scripted runs use `--bare`.** It skips the repo's hooks, MCP servers, and CLAUDE.md.
- **Stopping.** SIGINT ends a turn cleanly; SIGTERM leaves it unfinished. The signal must reach `claude`
  **inside** the sandbox: interrupting the `docker exec` / `openshell sandbox exec` client stops only the
  client. The worker sends `kill -INT` to the turn's process group in the sandbox (its pid recorded at
  start), waits about five seconds, then `kill -KILL`.
- **Background work.** A background Bash task is killed about five seconds after the final result, so
  anything the browser needs is started by our supervisor, not by the agent.
- **Costs.** When resuming, the reported total includes earlier turns, so we store per-turn deltas.
- **Subagents** keep their own context. Inside a turn they can research or review; the platform's agents
  (the lead and the specialists) stay for planning, and the Reviewer reads the PR.

Codex is **unverified**: its non-interactive flags, resume support, and event format must be checked
before a parser is written. Until then Codex gets the same session model with a turn-per-process
adapter and the earlier turns' summaries in its brief, as today.

## Sandbox backends

Both run the same image (`infra/coding/Dockerfile`), the repo at `/sandbox/repo`, and the agent as the
unprivileged `sandbox` user. The session model doesn't care which one runs it.

| | Docker (`DOTRIX_CODING_SANDBOX=docker`) | OpenShell (`openshell`) |
|---|---|---|
| Network | an internal network per sandbox; an egress proxy container allows the model API (and later registries) | the policy; the provider's proxy for the model API |
| Model key | in the agent's environment; only the model API is reachable | swapped in by OpenShell's proxy; the agent sees a placeholder |
| Filesystem | read-only system, a volume for `/sandbox`, tmpfs `/tmp` | Landlock: workdir and `/tmp` writable |
| Terminal (Phase C) | `docker exec -it` relayed over a WebSocket | `openshell sandbox exec` with a TTY |
| Registries and preview (Phase D) | entries in the egress allowlist; the preview port on the internal network, reached by the platform | the policy's network rules |
| Warm sandboxes | containers kept between turns, labelled `dotrix.run` / `dotrix.session` | sandboxes kept between turns |

`local` (a temporary folder, no isolation) stays for development and is refused in production.

## Model

A **session** is one issue's work. A **turn** is one request from a person and the agent's work on it.
The existing `CodingRun` becomes a turn: its `session_id` and `turn` already exist.

- `coding_sessions` (new): id, workspace_id, project_id, issue_id, tool, model, approval_mode, branch
  (`dotrix/<key>-<title>-<id>`, as today), pr_number, pr_url, state (`warm`, `idle`, `closed`),
  sandbox_name, transcript_key (blob storage), head_sha (the branch's last pushed commit),
  started_by_id, token_budget, time_budget_minutes, last_active_at.
- `coding_runs` (kept, one row per turn), extended: approval_mode, `awaiting_accept` and `accepted`
  statuses, head_sha (was `commit_sha`, renamed in the migration), diff_stat. `base_sha`,
  `files_changed`, `cost_usd` (now the turn's delta), tokens, `requested_by_id`, and `decided_by_id`
  stay. Existing rows map as: `awaiting_approval` → awaiting start, `pr_opened` → accepted (with the PR
  on the session), `no_changes`, `rejected`, `failed`, `stopped` unchanged.
- `coding_events` (new): session_id, run_id, seq, kind (`text`, `tool`, `step`, `error`,
  `permission_denied`, `retry`), payload (bounded), created_at. Replaces the 300-step cap on `events`.
  Live delivery goes through `RunStreams` (Redis in worker mode).

## Lifecycle

1. **Start.** Someone with `agents:code` starts a session on an issue (or assigns it to a coding tool)
   and picks a mode within their limits. The first turn waits for an approver in Manual and Accept
   edits; in Auto it's queued at once.
2. **Warm up.** The worker creates a sandbox, clones the session branch with its history if one exists
   (else the default branch) outside it, copies it in with no remote and no credentials, and restores
   the transcript. It writes the platform's settings, hooks, and MCP config, and passes the repo's
   `CLAUDE.md` / `AGENTS.md` as text (`--append-system-prompt-file`, marked as conventions and data).
3. **Turn.** The worker runs `claude -p --resume …` with the request. The agent edits and runs commands
   in `/sandbox/repo`. Events stream to `coding_events`; budgets are checked on every event.
4. **Commit.** When the turn ends, the worker commits everything in the sandbox as **one commit** for the
   turn (`KUN-12: <title> (turn 2)`), then pulls it out as a git bundle (size-capped like today's patch),
   verifies it sits on the session's head, and runs the guard on its paths.
5. **Accept.** In Manual, the turn waits in `awaiting_accept` with its diff; an approver accepts or
   rejects it. A rejected commit is reset in the sandbox, and the agent is told why on its next turn. In
   Accept edits and Auto this step is skipped.
6. **Push and PR.** An accepted commit is pushed to the session branch, never forced. **The first
   accepted turn opens the PR** and links it to the issue (which moves to `review`); later turns push to
   the same PR, and the issue's log says so. The Reviewer reads each pushed turn's diff. A person merges
   and closes the issue.
7. **Continue.** Follow-ups run in the same warm sandbox. A follow-up sent while the previous turn
   waits to be accepted queues behind it.
8. **Idle.** After `DOTRIX_CODING_IDLE_MINUTES` with no turn, the worker saves the transcript and deletes
   the sandbox; the session is `idle`. Pushed commits are already on the branch; an unaccepted turn's
   commit is kept as a bundle in blob storage with the transcript.
9. **Resume.** The next turn restores the sandbox from the branch (and any pending bundle) and the
   transcript, then resumes. If the branch was deleted, the session says so and offers a new branch.
10. **Stop.** SIGINT inside the sandbox, a grace of about five seconds, then SIGKILL. The turn records
    `stopped`; whatever it committed waits for accept like any other turn.
11. **Close.** When the PR is merged or closed (the webhook), or by hand, the session closes and its
    sandbox, transcript, and pending bundles are deleted.

Warm sandboxes are the cost centre, so the idle timeout and a cap on warm sandboxes per workspace matter
as much as the budgets.

## Transcripts

A transcript holds what the agent read and ran, so it is treated like the code it came from:

- stored in blob storage under the session's workspace, **encrypted** with the platform key, never in a
  repo;
- readable only by the session's viewers (above), never sent to another workspace's sandbox;
- deleted when the session closes or the project is deleted;
- treated as data on restore: a transcript an agent edited in its own sandbox only affects its own
  session.

## Monitoring

- **Events** are the source for the chat-style view: what the agent said, each tool use (command, file,
  search), permission denials, and retries. Subagent events carry `parent_tool_use_id`; the view nests
  them under the Agent call.
- **Changes** come from git, not from parsing the agent: per turn, the diff stat and files from the
  turn's commit; the working tree and the file tree from `git ls-files` at the head. The web already
  shows a session's repo, branches, commits, and changed files (Code tab, seeded data until it's wired).
- **Usage:** per-turn cost, tokens, and time, and the session total, for owners and admins.
- **System checks** at warm-up use `system/init`: the tools and MCP servers loaded. A missing MCP server
  (the browser, say) is shown, not silently skipped.

## Interactive surfaces

| Surface | Built as | Notes |
|---|---|---|
| Chat with the agent | Turns in the session | Chat's Code tab, a session per issue |
| Terminal | A PTY in the sandbox (per backend, above), relayed over a WebSocket | Read-only at first; typed input later, under the session's approval mode |
| File tree | `git ls-files` plus reads through the sandbox | Changed files marked, from git |
| Diff | The turn's commit, and the branch against its base | Accept or reject per turn in Manual; per file later |
| Browser and preview | Playwright MCP in the sandbox through `--mcp-config`; the dev server started by the supervisor on an allowed port | The preview is served through the platform, never an open port |
| Subagents | Claude Code's own, inside a turn | Their events are shown nested |

## Local-file projects

A project with no remote gets a bare repo on the platform, under `DOTRIX_CODE_DIR`, created when the
project is set up. It is the origin for sessions, where branches and accepted commits go, and the source
for the diff view. A project can later connect a GitHub repo; the platform then pushes the same branches
there.

## Phases

Each phase is usable on its own, and each is a PR.

**Phase 0: verify (before building).** With a model key, on the Docker sandbox:
- one real run end to end on a scratch repo (today's flow: brief, edit, patch, branch, PR);
- `--resume` with `--bare`: a transcript saved from one container and restored into another, same path;
- SIGINT delivered inside the container ends a turn cleanly and leaves a usable transcript;
- Codex's `exec --json` flags, events, and resume, if a key is available.

**Phase A1: events and Stop.**
- `coding_events` instead of the capped `events`; cost and tokens as per-turn deltas.
- Stop by signal inside the sandbox (SIGINT, then SIGKILL).

**Phase A2: turns in git, and approval modes.**
- The sandbox gets the session branch with history; one commit per turn; the bundle back through the
  guard; accept (Manual) or straight through (Accept edits, Auto); push, never forced; the first
  accepted turn opens the PR.
- Approval modes: the session's mode, the workspace's limit, the person's limit; reverts for a rejected
  pushed turn; the mode on each turn and in the audit log.
- Sessions private like conversations (the visibility rules above).

**Phase B: session lifecycle.**
- `coding_sessions`; warm, idle, and closed states; the transcript saved and restored (`--resume`);
  idle timeout and the warm-sandbox cap.
- Approvals for start and accept wired to Notifications (one item per turn waiting).

**Phase C: the workspace view.**
- Terminal (read-only), file tree, and diff in the session; subagent events nested; usage per session.
- The web's Code tab wired to the API (with Chat).

**Phase D: running apps.**
- Playwright MCP in the sandbox; the supervisor starts dev servers; preview through the platform.
- Registries and the preview port: the Docker egress allowlist and OpenShell's policy.

**Phase E: local-file projects and Codex.**
- A bare repo per local-file project, created at setup.
- The Codex adapter with resume, once Phase 0 has verified its protocol.

## Open questions

- **Idle timeout and warm-sandbox cap.** Starting values to measure, not decide in advance.
- **OpenShell snapshots.** Can a sandbox be paused or snapshotted, or do we always rebuild from the
  branch and transcript? We assume rebuild.
- **Typed terminal input.** Assumed to follow the session's approval mode: in Manual, typing needs the
  same approval as a turn.
