# pmagent

A reusable multi-agent project-management layer (PM agent orchestrating
Product / Architecture / Research / Reviewer / Documentation subagents) that
can be attached to *any* repo — not tied to one project.

## Install

```bash
pip install -e .
export ANTHROPIC_API_KEY="..."   # or OPENAI_API_KEY / GOOGLE_API_KEY
```

## Use

```bash
# Start a brand-new project
pmagent init ./my-new-repo

# Or attach to a repo you already have (imports its README if present)
pmagent connect ./existing-repo

# Feed it existing docs, any extension — normalized to markdown at ingest time
pmagent docs-add ./specs/old-prd.docx ./notes/postcode-research.pdf --project ./existing-repo

# Quick status, no interaction needed
pmagent brief --project my-app          # registered name, or a path — either works

# Full interactive session — Chat Mode by default; any write pauses for approval
pmagent chat --project my-app

# Kick off a task that runs alongside the above, on the same project
pmagent run "research the new postcode API" --project my-app --background
pmagent jobs --project my-app                       # see what's running/done
pmagent jobs-approve <job-id> --project my-app       # if it paused for Action Mode

pmagent projects                                     # every project you've init/connect-ed

# Task board
pmagent task create "Build postcode lookup" -d "Acceptance: ..." --priority high --due 2026-10-09 --depends-on TASK-1a2b3c4d
pmagent task list                    # open tasks, priority then due date (--all, --ready, --status, --assignee, --json)
pmagent task show TASK-1a2b3c4d
pmagent task update TASK-1a2b3c4d --status blocked --note "waiting on API key"
pmagent task comment TASK-1a2b3c4d "schema drafted"
pmagent task done TASK-1a2b3c4d      # or --review to hand back for review

# Coding tools (Claude Code, Codex) via MCP; nothing is added to the repo
pmagent handoff install --register
pmagent protect                      # re-apply git protection, report leaks

# Calendar
pmagent calendar export              # .pmagent/calendar.ics from every task's due/scheduled date
```

## Tasks and the coding-agent hand-off

Each task is one file, `.pmagent/tasks/TASK-xxxxxxxx.md`: YAML frontmatter
(status, priority, assignee, due, scheduled, depends_on, labels) plus a
markdown description and an append-only `## Log`. The files are the board.
There's no database, and `git log .pmagent/tasks/` is your task history.

Statuses are `todo -> in_progress -> review -> done`, plus `blocked`. A task is
*ready* when it's `todo`, every `depends_on` task is `done`, and it's either
unassigned or assigned to whoever's asking.

Claude Code and Codex remember nothing between sessions. They reach the board
and project knowledge through the MCP server (below) and work on a task only
when you tell them to: `claim_task`, `comment_task`, `set_task_blocked`, and
`submit_for_review`. The two tools get different assignee names, so they never
claim each other's work. Taking "the next task" resumes the tool's own
in-progress task before anything new, and claiming is serialized board-wide,
so parallel agents can't grab the same task.

The PM agent reads and changes the board through dedicated tools (`list_tasks`,
`get_task`, `create_task`, `update_task`, `comment_task`). The three write
tools are behind the same Action Mode approval as `write_file`. The CLI task
commands are *not* gated. They're how you and the coding agents move work
along. The gate exists to stop the PM agent writing unasked.

## Calendar

There's no separate calendar file. `due` and `scheduled` live on each task,
and `pmagent calendar export` renders them as iCalendar (`.pmagent/calendar.ics`)
with stable UIDs, so any calendar app can subscribe to or import it and
re-exports update events in place. It's gitignored because it's derived. Run it
from a git hook or cron if you want it always fresh.

## Concurrency

Several things can run against the same project at once — an interactive
`chat` plus one or more background `run` jobs, or several `run` jobs together:

- Every session/job gets its **own thread_id**, so LangGraph checkpoints each
  independently even though they share one SQLite file under
  `.pmagent/checkpoints.sqlite`.
- File writes go through `LockingFilesystemBackend`, which takes a per-file
  OS lock before writing — two writers touching the *same* file serialize
  instead of corrupting each other; unrelated files, and all reads, are
  never blocked.
- A background job that needs an Action Mode approval doesn't block waiting
  for a specific terminal to be watching it: it records `awaiting_approval`
  in `.pmagent/jobs/<id>.json` and exits. `pmagent jobs-approve` resumes it
  from anywhere, later.
- The PM agent's own prompt tells it to check `.pmagent/progress/` and
  `.pmagent/jobs/` before starting substantial work, so it doesn't duplicate
  something already in flight, and to delegate to several subagents in the
  same turn when their work is independent rather than doing it one at a time.

Two caveats worth knowing before you lean on this for anything important:

1. `LockingFilesystemBackend` wraps `FilesystemBackend`'s `write`/`edit`/
   `delete` (and async `awrite`/`aedit`/`adelete`), verified against
   deepagents 0.7.19. If you upgrade, re-check `dir(FilesystemBackend)`.
   Consider pinning `deepagents` in pyproject.toml.
2. SQLite handles concurrent access fine at this scale, but if you end up
   with many simultaneous jobs across many projects, swapping `SqliteSaver`
   for `PostgresSaver` (same interface, `langgraph-checkpoint-postgres`) is
   a same-day change, not a rewrite.

## Where this is heading (not built yet)

Right now every CLI command is its own OS process — fine for the concurrency
above, but each `pmagent chat` still holds its own copy of the compiled agent
graph in memory. If the desktop app needs to show a *live* view of a job
that's also visible in a terminal (rather than each just re-reading the same
files), the next step is a small local daemon (`pmagent serve`, a FastAPI/
WebSocket process) holding one job manager and one set of open sessions, with
the CLI and desktop app both becoming thin clients against it instead of each
spawning their own graphs. Worth doing once there's an actual desktop UI to
justify it — not before.

Everything project-specific lives in `<repo>/.pmagent/`: config, requirements,
architecture notes, decisions (ADRs), research, reviews, progress, tasks, and
ingested docs. That folder is the shared memory across every agent and session.

## `.pmagent/` never goes to GitHub

Project knowledge stays on your machine (and, once the hosted platform exists,
on the platform, with the local folder as a synced mirror). The code host only
ever sees code. `init` and `connect` apply three layers of protection, and
`pmagent protect` re-applies them (run it after `git init` or a fresh clone):

1. `.pmagent/.gitignore` containing `*`, so `git add .` never picks the folder up.
2. `.git/info/exclude` entries for `.pmagent/`, `AGENTS.md`, and `CLAUDE.md`:
   local to your clone, nothing committed.
3. A pre-commit hook that refuses commits containing `.pmagent/` or a hand-off
   file with pmagent's generated section, which catches `git add -f`. An existing
   pre-commit hook is kept and chained.

If git already tracks pmagent files from before, `protect` lists them and prints
the `git rm --cached` command. Earlier commits still contain them, so if the repo
is public, treat that content as exposed.

## Connecting Claude Code and Codex (MCP)

Because `.pmagent/` isn't in the repo, coding tools read it through an MCP server:

```bash
pmagent handoff install --register
```

This registers `pmagent mcp` in each installed tool's user-level config: Claude
Code's local scope (`~/.claude.json`) and Codex's `~/.codex/config.toml`. Nothing
is written into the repo (no `.mcp.json` or `.codex/config.toml`). Without
`--register` it prints the commands instead:

```bash
claude mcp add --transport stdio --scope local pmagent-<project> -- pmagent mcp --project /abs/path --assignee claude-code
codex mcp add pmagent-<project> -- pmagent mcp --project /abs/path --assignee codex
```

It also writes a short, git-excluded section into `CLAUDE.md` / `AGENTS.md`
pointing the tool at the server. If your repo already tracks its own
`AGENTS.md` or `CLAUDE.md`, pmagent leaves it untouched; the server's built-in
instructions carry the same guidance.

What the MCP server allows:

| Tools | Access |
| --- | --- |
| `project_overview`, `list_docs`, `read_doc`, `search_docs` | Read project knowledge (requirements, architecture, ADRs, research, reviews, progress, ingested docs) |
| `list_tasks`, `get_task` | Read the task board |
| `claim_task`, `comment_task`, `set_task_blocked`, `submit_for_review` | Move the tool's own task along: claim only when you tell it to, never close |

It cannot write knowledge docs; those change only through the PM agent in
Action Mode, with approval. Internals (`.locks/`, `jobs/`, checkpoints) are not
readable.

## Architecture

```
pmagent/config.py     — per-project config + folder skeleton (project-agnostic)
pmagent/ingest.py     — any-extension doc -> normalized markdown
pmagent/tasks.py      — task files: create/update/list, readiness, atomic claim
pmagent/ics.py        — calendar.ics from task dates
pmagent/handoff.py    — MCP registration + git-excluded AGENTS.md / CLAUDE.md sections
pmagent/mcp_server.py — MCP server: read project knowledge, move own tasks
pmagent/gitguard.py   — keeps .pmagent/ out of git (gitignore, exclude, hook)
pmagent/approvals.py  — describe + resume Action Mode interrupts (UI-agnostic)
pmagent/agent.py      — the PM + 5 subagents, Chat/Action mode gate (via interrupt_on)
pmagent/backend.py    — per-file locking over FilesystemBackend
pmagent/jobs*.py      — background jobs
pmagent/cli.py        — terminal front-end (the ONLY UI-specific file)
```

Everything except `cli.py` knows nothing about terminals. A
desktop app is a second front-end that imports the same three modules and
replaces `cli.py`'s `typer.prompt`/`echo` and the interrupt-drain loop with
native dialogs — no change needed to the agent logic itself. If the desktop
app and CLI need to share a live session (e.g. approve a write from the CLI
that the desktop app also shows), the next step is wrapping `build_agent` in
a small local FastAPI/WebSocket service so both front-ends talk to one
running engine instead of each holding their own graph instance.
