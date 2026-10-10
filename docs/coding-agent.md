# Coding agent: design

Status: proposed, 2026-10-10. Builds on the 5c coding runs (`apps/backend/src/pmagent_backend/modules/coding/`)
and replaces their one-shot model with a session per issue. The plan and checklist are in
[CLAUDE.md](../CLAUDE.md) under "Plan: coding agent". Claude Code facts below come from the headless
and sessions pages at code.claude.com/docs/en; anything marked **unverified** must be checked before
it is built on.

## Goal

A person assigns an issue, or starts a conversation about it, and a coding agent (Claude Code, or Codex)
works on it in its own sandbox. The person can follow the work live: what the agent says and does, the
terminal, the file tree, the diff, and a running app in a browser. They can continue the conversation
with follow-up turns. Every change is in git, and nothing leaves the sandbox until a person has
approved it. Approval is one step in the flow, not the whole design.

## Invariants

These hold whatever the implementation does.

1. **The sandbox is the blast radius.** The agent gets the repo, its tools, and the model API. Nothing else.
2. **No token ever enters a sandbox.** The worker fetches and pushes with installation tokens, outside it.
3. **Git is the record.** Every turn ends in commits. The history of the session is the history of the branch.
4. **A person approves changes before they leave the sandbox.** Starting a turn needs someone with the
   permission to instruct the coding agent. Changes reach the session branch only after an approver
   accepts the turn's diff. Opening or merging the PR stays with people (FR-26).
5. **Repo content is data.** Code, docs, `CLAUDE.md`, and `AGENTS.md` from a repo never change the
   platform's rules. The agent's instructions come from the platform, and the repo's come only as
   conventions to read.
6. **The platform's own hooks, settings, and MCP servers are the only ones that run** in a sandbox.
   A repo's `.claude/` and `.mcp.json` are never loaded.
7. **`.pmagent/` never enters a code repo.** The guard (`guard.py`) keeps refusing it.
8. **Every action is audited**, and every route is covered by the isolation suite.

## What we build on (Claude Code)

- **Headless turns.** `claude -p "<turn>" --resume <session_id> --output-format stream-json --verbose
  --include-partial-messages` runs one turn and streams its events. The final `result` carries
  `total_cost_usd` and usage.
- **Session state is the transcript.** Claude Code keeps each session as a transcript file. `--resume`
  continues it, from any directory on the machine, so the transcript can be restored into a new sandbox.
- **Scripted runs use `--bare`.** It skips the repo's hooks, MCP servers, and CLAUDE.md. The docs say it
  will become the default for `-p`.
- **Stopping.** SIGINT (or the Agent SDK's `interrupt()`) ends a turn cleanly. SIGTERM leaves it unfinished.
- **Background work.** A background Bash task is killed about five seconds after the final result, so
  anything the browser needs must be started by our supervisor, not by the agent.
- **Permissions.** `--permission-mode dontAsk` with `--allowedTools` pre-approves what the agent may use.
  `--permission-prompts none` stops anything waiting for a person. `auto` (a classifier per action) exists
  but we don't start with it.
- **Costs.** When resuming, the reported total includes earlier turns, so we store per-turn deltas.
- **Hooks** (`PostToolUse`, `SessionStart`, `SessionEnd`, `PermissionRequest`) exist for event
  handling. We use them for checkpoints and events, from settings the platform supplies.
- **Subagents** keep their own context. Inside a turn they can do research or review; the platform's
  agents (PM, specialists) stay for planning and the Reviewer.

Codex is **unverified**: its non-interactive flags, resume support, and event format must be checked
before a parser is written. Until then Codex gets the same session model with a turn-per-process adapter
and no resume promise.

## Model

A **session** is one issue's work. A **turn** is one message from a person and the agent's reply. The
existing `CodingRun` is a turn; its `session_id` and `turn` fields already exist.

- `coding_sessions`: id, workspace_id, project_id, issue_id, tool (claude-code, codex), model,
  branch (`pmagent/<key>-<id>`), pr_number, state (`warm`, `idle`, `closed`), sandbox_name,
  `transcript_key` (blob storage), `snapshot_sha` (last commit pushed to the branch), created_by,
  `token_budget`, `time_budget_minutes`, `last_active_at`.
- `coding_turns` (the existing `CodingRun`, extended): session_id, turn, status
  (`awaiting_start`, `queued`, `running`, `awaiting_accept`, `accepted`, `rejected`, `stopped`, `failed`),
  request, brief summary, `base_sha`, `head_sha`, `diff_stat`, `cost_usd` (the turn's delta),
  `input_tokens`, `output_tokens`, approved_by, instructed_by.
- `coding_events`: session_id, turn_id, seq, kind (`text`, `tool`, `step`, `error`, `permission_denied`,
  `retry`, `checkpoint`), payload (bounded), created_at. Replaces the 300-step cap on `events`. Live
  delivery goes through `RunStreams` (Redis in worker mode).

## Lifecycle

1. **Start.** Someone with permission starts a session on an issue. A turn is created in
   `awaiting_start`. An approver (or the instructor, where policy allows) starts it.
2. **Warm up.** The worker creates a sandbox from the coding image under the policy. It clones the
   session branch with its history if one exists, otherwise the default branch, and restores the transcript.
   The platform writes `CLAUDE.md` and the settings and MCP config into the sandbox.
3. **Turn.** The worker runs `claude -p --resume <id> …` (or the Codex equivalent) with the request. The
   agent edits and runs commands in `/sandbox/repo`. Hooks commit each change on a local branch in the
   sandbox, with messages naming the turn. Events stream to `coding_events`. Budgets are checked on every event.
4. **Accept.** When the turn ends, the platform builds the turn's diff from `base_sha` to `head_sha`. An
   approver reviews it in the diff view and accepts or rejects. Accepted commits are pushed to the session
   branch, never forced. Rejected ones are reverted in the sandbox, and the transcript records why.
5. **Continue.** Follow-up turns start from the same warm sandbox. Sending the next message is allowed
   while the previous turn is `awaiting_accept`, but it queues behind it.
6. **Idle.** After `CODING_IDLE_MINUTES` with no turn, the worker snapshots: it pushes accepted commits
   (already done), saves the transcript to blob storage, and deletes the sandbox. The session is `idle`.
7. **Resume.** The next turn restores the sandbox from the branch and transcript, then resumes. If the
   branch was deleted, the session says so and offers a new branch from the default branch.
8. **Close.** Opening the PR (on accept, or on request) links it to the issue and moves the issue to
   `review`. A person closes the issue. Merging stays with people.
9. **Stop.** SIGINT to the process group, a grace period of about five seconds, then SIGKILL. The turn
   records `stopped` and keeps any accepted work.

Warm sandboxes are the cost centre, so the idle timeout and a cap on warm sandboxes per workspace matter
as much as the budgets.

## Monitoring

- **Events** are the source for the chat-style view: what the agent said, each tool use (command, file,
  search), permission denials, retries, and checkpoints. Subagent events carry `parent_tool_use_id`, and the
  view nests them under the Agent call.
- **Changes** come from git, not from parsing the agent: `git diff --stat` and file lists per turn, and the
  file tree from `git ls-files` at `HEAD`. Refreshed after each turn and on demand.
- **Usage**: per-turn `cost_usd`, tokens, time, and the session total, for owners and admins.
- **System checks** at warm-up use `system/init`: the tools and MCP servers loaded. A missing MCP server
  (the browser, say) is shown, not silently skipped.

## Interactive surfaces

| Surface | Built as | Notes |
|---|---|---|
| Chat with the agent | Turns in the session | The existing Chat tab gets a Coding view per session |
| Terminal | A PTY over `openshell sandbox exec` with a TTY (`--no-tty` changes), relayed over WebSocket | Read-only at first; typed input later, with the same approval rules as a turn |
| File tree | `git ls-files` plus reads through the sandbox | Changed files marked, from git |
| Diff | `git diff base_sha..head_sha` and the working tree | Accept or reject per turn; per file later |
| Browser and preview | Playwright MCP in the sandbox through `--mcp-config`; the app's dev server started by the supervisor on an allowed port | The preview is served through the platform, not an open port |
| Subagents | Claude Code's own, inside a turn | Their events are shown nested |

Most of these are MCP servers or existing platform pieces, not new agent features.

## Sandbox and security

- **Policy:** writable workdir and `/tmp`, read-only system (Landlock), no network except the model API,
  package registries (for installing dependencies), and the preview port. The model provider is attached
  per session, and the key stays behind OpenShell's proxy.
- **Settings:** `--bare`, with the platform's `--settings` (hooks, permission rules) and `--mcp-config`
  (Playwright and our tools). The repo's `.claude/` and `.mcp.json` are not used. `CLAUDE.md` and `AGENTS.md`
  are passed as text with `--append-system-prompt-file`, marked as conventions and data.
- **Permissions:** `dontAsk` with a fixed `--allowedTools` list, `--permission-prompts none`. Denials become
  events the person can see.
- **Budgets:** per session tokens and time, and per workspace warm-sandbox count. Hitting a budget stops the
  turn cleanly.
- **Isolation:** every session route gets a row in the isolation suite's `World`. The sandbox never
  receives another workspace's branch, transcript, or key.

## Local-file projects

A project with no remote gets a bare repo on the platform, under `PMAGENT_CODE_DIR`, created when the
project is set up. It is the origin for sessions, the place branches and accepted commits go, and the
source for the diff view. A project can later connect a GitHub repo; the platform then pushes the same
branches there.

## Phases

Each phase is usable on its own, and each one is a PR.

**Phase A: correct the loop (the foundation).**
- Sandbox clones the session branch with history, and no credentials. Turn commits are local.
- Worker pulls the turn's commits as a bundle; the existing guard checks them; accepted commits are pushed.
- Per-turn `claude -p --resume`, with the transcript saved to blob storage after each turn and restored into a new sandbox.
- `--bare` with platform settings and MCP config; `CLAUDE.md` passed as text.
- Stop sends SIGINT, then SIGKILL.
- Events in `coding_events`; cost as per-turn deltas.

**Phase B: session lifecycle.**
- `coding_sessions`; warm, idle, and closed states; idle snapshot; restore on the next turn.
- Accept and reject per turn, with the diff.
- Per-turn approval wired to the existing approvals and Notifications.

**Phase C: the workspace view.**
- Terminal (read-only), file tree, and diff in the session view.
- Subagent events nested under their Agent call.
- Usage per session for owners and admins.

**Phase D: running apps.**
- Playwright MCP in the sandbox; the supervisor starts dev servers; preview through the platform.
- Network policy for registries and the preview port, tested against OpenShell.

**Phase E: local-file projects and Codex.**
- Bare repo per local-file project, created at setup.
- Codex adapter after its protocol is verified.

## Open questions and unverified points

- **Resume across paths.** Does `--resume` find a transcript when the project path differs between sandboxes?
  Test it before Phase A is merged.
- **OpenShell snapshots.** Can a sandbox be paused or snapshotted, or do we always rebuild from the branch?
  We assume rebuild. Check the OpenShell CLI.
- **Codex.** Non-interactive flags, resume, and event format.
- **Idle timeout and warm-sandbox cap.** Starting values to measure, not decide in advance.
- **Typed terminal input.** Whether a person's typing needs the same approval as a turn. Assumed yes.
