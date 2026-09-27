"""CLI front-end for the PM Agent System.

Intentionally thin: config / ingest / tasks / ics / approvals / agent contain
all the logic and know nothing about terminals. A later desktop app imports
those same modules and swaps out typer.prompt/echo + the interrupt loop below
for native UI.

Task commands (`task ...`, `next`) are direct board operations, NOT agent
calls, so they don't pass through the Action Mode gate. That's deliberate:
they're how humans and coding agents (Claude Code, Codex) move work along.
The gate exists to stop the *PM agent* from writing without being asked.
"""
from __future__ import annotations

import json
import os
import uuid

import typer
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from pmagent_engine import approvals, registry
from pmagent_engine import tasks as T
from pmagent_engine.agent import build_agent
from pmagent_engine.config import ProjectConfig, scaffold
from pmagent_engine.gitguard import protect as git_protect
from pmagent_engine.handoff import install_handoff
from pmagent_engine.ics import export_calendar
from pmagent_engine.ingest import ingest_doc
from pmagent_engine.jobs import get_job, list_jobs, resume_job, start_job

from .agent_client import Outcome, PlatformAgent
from .board import CODING_AGENTS, PlatformBoard
from .platform import (
    KeychainUnavailable,
    KeyringStore,
    PlatformClient,
    PlatformError,
    api_url,
    device_login,
)
from .sync import LinkState, find_project, find_workspace, pull

app = typer.Typer(help="Multi-agent project management for any repo (init or connect).")
task_app = typer.Typer(help="Create, list, and update tasks on the project board.")
calendar_app = typer.Typer(help="Calendar views derived from task due/scheduled dates.")
handoff_app = typer.Typer(help="Hand-off instructions for coding agents (Claude Code, Codex).")
app.add_typer(task_app, name="task")
app.add_typer(calendar_app, name="calendar")
app.add_typer(handoff_app, name="handoff")
issue_app = typer.Typer(help="Work the platform issue board (needs `pmagent link`).")
app.add_typer(issue_app, name="issue")

ProjectOpt = typer.Option(".", "--project", "-p", help="Registered project name or path.")
AuthorOpt = typer.Option("human", "--author", "-a", help="Who is making this change (shown in the task log).")


def _resolve_project(project: str) -> ProjectConfig:
    """`project` may be a registered name (from `init`/`connect`) or a path."""
    return ProjectConfig.load(os.path.abspath(registry.resolve(project)))


def _echo_protection(report: dict) -> None:
    if not report.get("git_repo"):
        typer.echo(f"  .pmagent/ kept out of git: {report.get('note')}")
        return
    typer.echo(f"  .pmagent/ kept out of git: folder .gitignore, .git/info/exclude "
               f"({report['exclude']}), pre-commit hook ({report['hook']})")
    leaks = report.get("tracked_leaks") or []
    if leaks:
        typer.secho(
            "  WARNING: git already tracks pmagent files (committed earlier):\n    "
            + "\n    ".join(leaks[:10]) + ("\n    ..." if len(leaks) > 10 else "")
            + "\n  Remove them from the repo (files stay on disk):\n"
            "    git rm -r --cached " + " ".join(sorted({p.split("/")[0] for p in leaks}))
            + " && git commit -m 'Stop tracking pmagent files'\n"
            "  They remain in earlier commits; if the repo is public, treat that content as exposed.",
            fg=typer.colors.YELLOW,
        )


def _fail(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Project setup
# ---------------------------------------------------------------------------
@app.command()
def init(path: str = typer.Argument(".", help="Repo root to initialize.")):
    """Set up a NEW project: create .pmagent/ from scratch."""
    path = os.path.abspath(path)
    name = typer.prompt("Project name")
    description = typer.prompt("One-line description", default="")
    config = ProjectConfig(name=name, description=description, root_dir=path)
    report = scaffold(config)
    registry.register(name, path)
    typer.echo(f"Initialized {config.pmagent_dir} (registered as '{name}')")
    _echo_protection(report)
    typer.echo("Tip: `pmagent handoff install --register` connects Claude Code / Codex via MCP.")


@app.command()
def connect(path: str = typer.Argument(..., help="Existing repo to connect.")):
    """Connect an EXISTING repo: scaffold .pmagent/ alongside it, importing README if present."""
    path = os.path.abspath(path)
    name = typer.prompt("Project name", default=os.path.basename(path.rstrip("/")))
    description = typer.prompt("One-line description", default="")
    config = ProjectConfig(name=name, description=description, root_dir=path)

    readme = None
    for candidate in ("README.md", "readme.md", "README.rst"):
        candidate_path = os.path.join(path, candidate)
        if os.path.exists(candidate_path):
            with open(candidate_path) as f:
                readme = f.read()
            break

    report = scaffold(config, existing_readme=readme)
    registry.register(name, path)
    suffix = " (README imported into project.md)" if readme else ""
    typer.echo(f"Connected {path} -> {config.pmagent_dir}{suffix}, registered as '{name}'")
    _echo_protection(report)


@app.command()
def projects():
    """List every project you've `init` or `connect`-ed, by name."""
    known = registry.list_projects()
    if not known:
        typer.echo("No projects registered yet. Run `pmagent init` or `pmagent connect`.")
        return
    for name, path in known.items():
        typer.echo(f"{name}  ->  {path}")


@app.command()
def protect(project: str = ProjectOpt):
    """(Re)apply the protections that keep .pmagent/ out of git, and report
    any pmagent files git already tracks. Run after `git init` or cloning."""
    config = _resolve_project(project)
    _echo_protection(git_protect(config.root_dir, config.pmagent_dir))


@app.command("mcp")
def mcp_cmd(
    project: str = ProjectOpt,
    assignee: str = typer.Option("claude-code", "--assignee",
                                 help='Who this client acts as on the board, e.g. "claude-code" or "codex".'),
):
    """Run the MCP server (stdio) for Claude Code, Codex, or any MCP client.
    Normally started by the tool itself; see `pmagent handoff install`."""
    from .mcp_server import run as run_mcp  # lazy: only this command needs the mcp package
    run_mcp(_resolve_project(project), assignee)


@app.command("docs-add")
def docs_add(
    files: list[str] = typer.Argument(..., help="Docs to ingest, any extension (docx, pdf, pptx, xlsx, md, txt...)."),
    project: str = ProjectOpt,
):
    """Ingest one or more project docs, normalized to markdown regardless of source format."""
    config = _resolve_project(project)
    for f in files:
        normalized = ingest_doc(config, f)
        typer.echo(f"  {f} -> .pmagent/{normalized}")


# ---------------------------------------------------------------------------
# Talking to the PM agent
# ---------------------------------------------------------------------------
LocalOpt = typer.Option(False, "--local", help="Use the local engine even if this repo is linked.")


@app.command()
def brief(project: str = ProjectOpt, local: bool = LocalOpt):
    """One-shot: ask the PM agent for a project briefing (Chat Mode, no writes expected).
    On a linked repo this is the platform's briefing, which is read-only."""
    config = _resolve_project(project)
    if not local and LinkState.load(config.pmagent_dir) is not None:
        _platform_brief(project)
        return
    agent = build_agent(config, checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    result = agent.invoke({"messages": [{"role": "user", "content": "Give me my project briefing."}]}, cfg)
    if approvals.has_pending(result):
        # A briefing shouldn't write. If it tries, refuse rather than prompt.
        result = agent.invoke(approvals.resume_command(
            result, "reject", "Briefings are read-only. Don't write anything."), cfg)
    typer.echo(result["messages"][-1].content)


@app.command()
def chat(
    project: str = ProjectOpt,
    local: bool = LocalOpt,
    thread: str | None = typer.Option(None, "--thread", help="Continue a platform conversation."),
):
    """Interactive session. Any write pauses for your approval. That pause IS Action Mode.

    On a linked repo you talk to the platform's agents: every change they want is shown
    here (with a diff for files) and you approve or reject it inline. Otherwise it runs
    the local engine; safe alongside `pmagent run --background` jobs and coding agents."""
    config = _resolve_project(project)
    if not local and LinkState.load(config.pmagent_dir) is not None:
        _platform_chat(project, thread)
        return
    checkpoint_path = os.path.join(config.pmagent_dir, "checkpoints.sqlite")

    with SqliteSaver.from_conn_string(checkpoint_path) as checkpointer:
        agent = build_agent(config, checkpointer=checkpointer)
        cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}

        typer.echo(f"Connected to {config.name}. Ctrl+C to exit.\n")
        while True:
            try:
                user_msg = typer.prompt(">")
            except (KeyboardInterrupt, EOFError, typer.Abort):
                break
            result = agent.invoke({"messages": [{"role": "user", "content": user_msg}]}, cfg)
            _drain_interrupts(agent, result, cfg)


def _drain_interrupts(agent, result: dict, cfg: dict) -> None:
    """Show every pending action, collect one decision each, resume. Repeat
    until the run finishes (a resumed run can pause again)."""
    while approvals.has_pending(result):
        actions = approvals.pending_actions(result)
        decisions, message = [], None
        for i, action in enumerate(actions, 1):
            typer.echo(f"\n[Action requested {i}/{len(actions)}]\n{approvals.format_action(action)}\n")
            d = typer.prompt("approve / reject", default="approve").strip().lower()
            while d not in ("approve", "reject"):
                d = typer.prompt("Please type approve or reject", default="approve").strip().lower()
            if d == "reject" and message is None:
                message = typer.prompt("Why? (sent to the agent)", default="", show_default=False) or None
            decisions.append(d)
        result = agent.invoke(approvals.resume_command(actions, decisions, message), cfg)
    typer.echo(f"\n{result['messages'][-1].content}\n")


# ---------------------------------------------------------------------------
# Background jobs
# ---------------------------------------------------------------------------
@app.command()
def run(
    instruction: str = typer.Argument(..., help="What should the PM agent do?"),
    project: str = ProjectOpt,
    background: bool = typer.Option(
        False, "--background", "-b",
        help="Return immediately; check progress with `pmagent jobs`. Several can run at once.",
    ),
):
    """Kick off a task without an interactive session. Can run concurrently
    with `pmagent chat` or other `run` jobs on the same project."""
    config = _resolve_project(project)
    job = start_job(config, instruction, background)
    if background:
        typer.echo(f"Started job {job['id']} ({job['status']}). Log: {job['log_path']}")
    elif job["status"] == "awaiting_approval":
        typer.echo(f"[job {job['id']}] awaiting approval:")
        for a in job.get("pending_actions") or []:
            typer.echo(approvals.format_action(a) + "\n")
        typer.echo(f"Resume with: pmagent jobs-approve {job['id']} --project {project}")
    elif job["status"] == "failed":
        _fail(f"[job {job['id']}] failed: {job.get('error')}")
    else:
        typer.echo(job.get("result", ""))


@app.command("jobs")
def jobs_list(project: str = ProjectOpt):
    """List every job for a project: running, awaiting approval, failed, or done."""
    config = _resolve_project(project)
    jobs = list_jobs(config)
    if not jobs:
        typer.echo('No jobs yet. Start one with `pmagent run "..." --background`.')
        return
    for job in jobs:
        typer.echo(f"{job['id']}  [{job['status']}]  {job['instruction']}")


@app.command("jobs-approve")
def jobs_approve(
    job_id: str = typer.Argument(...),
    project: str = ProjectOpt,
    reject: bool = typer.Option(False, "--reject", help="Reject instead of approve."),
    message: str | None = typer.Option(None, "--message", "-m", help="Reason, sent to the agent on reject."),
    background: bool = typer.Option(True, "--background/--foreground"),
):
    """Approve or reject everything a paused job is waiting on, from any terminal."""
    config = _resolve_project(project)
    pending = get_job(config, job_id).get("pending_actions") or []
    for a in pending:
        typer.echo(approvals.format_action(a) + "\n")
    decision = "reject" if reject else "approve"
    try:
        job = resume_job(config, job_id, decision, background, reject_message=message)
    except ValueError as e:
        _fail(str(e))
    typer.echo(f"Job {job_id} -> {job['status']}")


# ---------------------------------------------------------------------------
# Task board
# ---------------------------------------------------------------------------
def _print_task_row(t: T.Task) -> None:
    due = f"due {t.due}" if t.due else ""
    who = t.assignee or "unassigned"
    deps = f"after {','.join(t.depends_on)}" if t.depends_on else ""
    extras = "  ".join(x for x in (due, deps) if x)
    typer.echo(f"{t.id}  [{t.status:<11}] {t.priority:<6} {who:<12} {t.title}  {extras}".rstrip())


def _emit(task: T.Task, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps({"task": task.to_dict()}, indent=2))
    else:
        _print_task_row(task)


@task_app.command("create")
def task_create(
    title: str = typer.Argument(...),
    description: str = typer.Option("", "--description", "-d"),
    priority: str = typer.Option("medium", "--priority", help="low | medium | high | urgent"),
    assignee: str | None = typer.Option(None, "--assignee"),
    due: str | None = typer.Option(None, "--due", help="YYYY-MM-DD"),
    scheduled: str | None = typer.Option(None, "--scheduled", help="YYYY-MM-DD or ISO datetime"),
    depends_on: str | None = typer.Option(None, "--depends-on", help="Comma-separated task ids"),
    labels: str | None = typer.Option(None, "--labels", help="Comma-separated"),
    author: str = AuthorOpt,
    as_json: bool = typer.Option(False, "--json"),
    project: str = ProjectOpt,
):
    """Create a task."""
    config = _resolve_project(project)
    try:
        t = T.create_task(config, title, description=description, priority=priority,
                          assignee=assignee, due=due, scheduled=scheduled,
                          depends_on=depends_on, labels=labels, author=author)
    except ValueError as e:
        _fail(str(e))
    _emit(t, as_json)


@task_app.command("list")
def task_list(
    status: str | None = typer.Option(None, "--status"),
    assignee: str | None = typer.Option(None, "--assignee"),
    label: str | None = typer.Option(None, "--label"),
    all_: bool = typer.Option(False, "--all", help="Include done tasks."),
    ready: bool = typer.Option(False, "--ready", help="Only tasks that could start right now."),
    as_json: bool = typer.Option(False, "--json"),
    project: str = ProjectOpt,
):
    """List tasks, highest priority first (done tasks hidden unless --all or --status done)."""
    config = _resolve_project(project)
    if ready:
        items = T.ready_tasks(config, assignee)
    else:
        items = T.list_tasks(config, status=status, assignee=assignee, label=label,
                             include_done=all_ or status == "done")
    if as_json:
        typer.echo(json.dumps({"tasks": [t.to_dict() for t in items]}, indent=2))
        return
    if not items:
        typer.echo("No matching tasks.")
    for t in items:
        _print_task_row(t)


@task_app.command("show")
def task_show(
    task_id: str = typer.Argument(...),
    as_json: bool = typer.Option(False, "--json"),
    project: str = ProjectOpt,
):
    """Show one task in full, including its log."""
    config = _resolve_project(project)
    try:
        t = T.get_task(config, task_id)
    except (FileNotFoundError, ValueError) as e:
        _fail(str(e))
    if as_json:
        typer.echo(json.dumps({"task": t.to_dict()}, indent=2))
    else:
        typer.echo(t.to_markdown())


@task_app.command("update")
def task_update(
    task_id: str = typer.Argument(...),
    status: str | None = typer.Option(None, "--status"),
    priority: str | None = typer.Option(None, "--priority"),
    assignee: str | None = typer.Option(None, "--assignee"),
    due: str | None = typer.Option(None, "--due"),
    scheduled: str | None = typer.Option(None, "--scheduled"),
    depends_on: str | None = typer.Option(None, "--depends-on"),
    labels: str | None = typer.Option(None, "--labels"),
    title: str | None = typer.Option(None, "--title"),
    description: str | None = typer.Option(None, "--description", "-d"),
    note: str | None = typer.Option(None, "--note", help="Appended to the task log."),
    author: str = AuthorOpt,
    as_json: bool = typer.Option(False, "--json"),
    project: str = ProjectOpt,
):
    """Change fields on a task. Only the flags you pass change."""
    config = _resolve_project(project)
    try:
        t = T.update_task(config, task_id, author=author, note=note, status=status,
                          priority=priority, assignee=assignee, due=due, scheduled=scheduled,
                          depends_on=depends_on, labels=labels, title=title,
                          description=description)
    except (FileNotFoundError, ValueError) as e:
        _fail(str(e))
    _emit(t, as_json)


@task_app.command("comment")
def task_comment(
    task_id: str = typer.Argument(...),
    text: str = typer.Argument(...),
    author: str = AuthorOpt,
    project: str = ProjectOpt,
):
    """Append a comment to a task's log."""
    config = _resolve_project(project)
    try:
        T.comment_task(config, task_id, text, author=author)
    except (FileNotFoundError, ValueError) as e:
        _fail(str(e))
    typer.echo(f"Commented on {T.norm_id(task_id)}")


@task_app.command("done")
def task_done(
    task_id: str = typer.Argument(...),
    review: bool = typer.Option(False, "--review", help="Hand back for review instead of closing."),
    note: str | None = typer.Option(None, "--note"),
    author: str = AuthorOpt,
    as_json: bool = typer.Option(False, "--json"),
    project: str = ProjectOpt,
):
    """Mark a task done (or, with --review, ready for review)."""
    config = _resolve_project(project)
    try:
        t = T.complete_task(config, task_id, author=author, note=note, to_review=review)
    except (FileNotFoundError, ValueError) as e:
        _fail(str(e))
    _emit(t, as_json)


@app.command("next")
def next_cmd(
    assignee: str = typer.Option(..., "--assignee", help='e.g. "claude-code" or "codex"'),
    claim: bool = typer.Option(False, "--claim", help="Assign it and move it to in_progress."),
    as_json: bool = typer.Option(False, "--json"),
    project: str = ProjectOpt,
):
    """What should ASSIGNEE work on next? Resumes its in-progress task first.

    Coding agents run this only when the user asks them to take the next task."""
    config = _resolve_project(project)
    t = T.next_task(config, assignee, claim=claim)
    if as_json:
        typer.echo(json.dumps({"task": t.to_dict() if t else None}, indent=2))
    elif t is None:
        typer.echo(f"Nothing ready for {assignee}.")
    else:
        typer.echo(t.to_markdown())


# ---------------------------------------------------------------------------
# Calendar + hand-off
# ---------------------------------------------------------------------------
@calendar_app.command("export")
def calendar_export(
    out: str | None = typer.Option(None, "--out", "-o", help="Default: .pmagent/calendar.ics"),
    open_only: bool = typer.Option(False, "--open-only", help="Leave done tasks off the calendar."),
    project: str = ProjectOpt,
):
    """Write an .ics file of every task with a due or scheduled date."""
    config = _resolve_project(project)
    path, n = export_calendar(config, out, include_done=not open_only)
    typer.echo(f"Wrote {n} task(s) to {path}")


@handoff_app.command("install")
def handoff_install(
    codex_assignee: str = typer.Option("codex", "--codex-assignee"),
    claude_assignee: str = typer.Option("claude-code", "--claude-assignee"),
    register: bool = typer.Option(False, "--register",
                                  help="Also register the MCP server with installed claude / codex CLIs."),
    project: str = ProjectOpt,
):
    """Connect Claude Code and Codex: git-excluded CLAUDE.md / AGENTS.md sections
    plus MCP registration in each tool's user-level config (nothing in the repo)."""
    config = _resolve_project(project)
    for fname, what in install_handoff(config, codex_assignee=codex_assignee,
                                       claude_assignee=claude_assignee,
                                       register_mcp=register).items():
        typer.echo(f"{fname}: {what}")

# ---------------------------------------------------------------------------
# Talking to the platform's agents (linked repos)
# ---------------------------------------------------------------------------
_DIFF_LINES = 60
_PREVIEW_LINES = 14


def _echo_diff(diff: str, limit: int | None = _DIFF_LINES) -> None:
    lines = diff.splitlines()
    for line in lines[:limit] if limit else lines:
        color = typer.colors.GREEN if line.startswith("+") and not line.startswith("+++") else (
            typer.colors.RED if line.startswith("-") and not line.startswith("---") else None
        )
        typer.secho(f"    {line}", fg=color)
    if limit and len(lines) > limit:
        typer.secho(f"    … {len(lines) - limit} more line(s); press v to see all", dim=True)


def _echo_approval(approval: dict, full: bool = False) -> None:
    args = approval.get("args") or {}
    if approval.get("diff"):
        _echo_diff(approval["diff"], None if full else _DIFF_LINES)
    elif approval["tool"] == "create_issue":
        facts = ", ".join(f"{k} {args[k]}" for k in ("priority", "parent", "assignee") if args.get(k))
        if facts:
            typer.echo(f"    {facts}")
        description = (args.get("description") or "").splitlines()
        for line in description if full else description[:_PREVIEW_LINES]:
            typer.echo(f"    {line}")
        if not full and len(description) > _PREVIEW_LINES:
            typer.secho("    … press v to see all", dim=True)
    else:
        shown = {k: v for k, v in args.items() if k not in ("key", "file_path")}
        text = json.dumps(shown, indent=2, ensure_ascii=False)
        typer.echo("\n".join(f"    {line}" for line in (text if full else text[:1500]).splitlines()))


def _ask_decision(approval: dict, index: int, total: int):
    target = f" -> {approval['target']}" if approval.get("target") else ""
    typer.secho(f"\n[{index}/{total}] The agents want to: {approval['tool']}{target}", bold=True)
    _echo_approval(approval)
    options = "[a]pprove, [r]eject" + (", [A]pprove all" if total > 1 else "") + ", [v]iew in full"
    while True:
        choice = typer.prompt(options, default="a", show_default=False).strip()
        if choice in ("a", "approve"):
            return ("approve", None)
        if choice == "A" and total > 1:
            return "approve-all"
        if choice in ("r", "reject"):
            reason = typer.prompt("Why? (sent back to the agent)", default="", show_default=False).strip()
            return ("reject", reason or None)
        if choice == "v":
            _echo_approval(approval, full=True)


def _echo_outcome(outcome: Outcome) -> None:
    run = outcome.run
    if outcome.left_waiting:
        typer.secho(
            "\nYour role can't approve changes. The run is waiting: someone with approve "
            f"permission can decide it in the web app (run {run['id']}).",
            fg=typer.colors.YELLOW,
        )
    elif run["status"] == "failed":
        typer.secho(f"\nThe run failed: {run.get('error')}", fg=typer.colors.RED)
    else:
        decided = [a for a in run.get("approvals", []) if a["status"] != "pending"]
        if decided:
            approved = sum(a["status"] == "approved" for a in decided)
            typer.secho(f"\n({approved} change(s) approved, {len(decided) - approved} rejected)", dim=True)
        typer.echo(f"\n{run.get('reply') or ''}\n")


def _platform_agent(project: str) -> tuple[LinkState, PlatformAgent]:
    _, state, client = _linked(project)
    return state, PlatformAgent(client, state)


def _platform_brief(project: str) -> None:
    _, agent = _platform_agent(project)
    typer.secho("Preparing your briefing…", dim=True)
    run = _platform_call(agent.briefing)
    outcome = Outcome(_platform_call(lambda: agent.wait(run)))
    _echo_outcome(outcome)
    if outcome.status == "failed":
        raise typer.Exit(1)


def _platform_chat(project: str, thread: str | None) -> None:
    state, agent = _platform_agent(project)
    typer.echo(
        f"Talking to the {state.project_key} team ({state.project_name}) on the platform. "
        "Changes wait for your approval. /new starts a new conversation, /quit exits.\n"
    )
    while True:
        try:
            message = typer.prompt(">").strip()
        except (KeyboardInterrupt, EOFError, typer.Abort):
            break
        if message in ("/quit", "/exit", "/q"):
            break
        if message == "/new":
            thread = None
            typer.echo("New conversation.")
            continue
        if not message:
            continue
        try:
            run = agent.start(message, thread)
            thread = run["thread_id"]
            typer.secho("(working…)", dim=True)
            _echo_outcome(agent.converse(run, _ask_decision))
        except (PlatformError, TimeoutError) as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
    if thread:
        typer.secho(f"Continue this conversation with: pmagent chat --thread {thread}", dim=True)


# ---------------------------------------------------------------------------
# Platform: sign in, link a repo, mirror .pmagent/, work the issue board
# ---------------------------------------------------------------------------
ApiUrlOpt = typer.Option(None, "--api-url", help="Platform API URL (default $PMAGENT_API_URL or http://127.0.0.1:8000).")
AsAgentOpt = typer.Option(None, "--as", help=f"Act as a coding agent: {', '.join(CODING_AGENTS)}.")


def _platform_call(fn):
    """Run a platform call and turn API errors into a clean message and exit code."""
    try:
        return fn()
    except (PlatformError, ValueError) as exc:
        _fail(str(exc))


def _linked(project: str) -> tuple[ProjectConfig, LinkState, PlatformClient]:
    config = _resolve_project(project)
    state = LinkState.load(config.pmagent_dir)
    if state is None:
        _fail(f"{config.root_dir} isn't linked to the platform. Run `pmagent link --workspace <slug> --project <KEY>`.")
    return config, state, _platform_call(lambda: PlatformClient.signed_in(state.api_url))


def _echo_pull(result) -> None:
    typer.echo(f"Pulled revision {result.revision}: {len(result.updated)} updated, {len(result.deleted)} deleted")
    if result.conflicts:
        typer.secho(
            f"  {len(result.conflicts)} file(s) changed locally and on the platform; left as they are:\n    "
            + "\n    ".join(result.conflicts)
            + "\n  The platform is the source of truth: `pmagent pull --force` takes its versions.",
            fg=typer.colors.YELLOW,
        )


@app.command()
def login(
    url: str | None = ApiUrlOpt,
    no_browser: bool = typer.Option(False, "--no-browser", help="Just print the link."),
):
    """Sign in to the platform with a one-time code you approve in the browser.
    The token is stored in your OS keychain, never in a file."""
    target = api_url(url)
    client = PlatformClient(target)

    def show(code: str, uri: str, complete: str) -> None:
        typer.echo(f"To sign in, open {uri} and enter code:  {code}")
        typer.echo(f"(or open {complete})  Waiting for approval…")

    credential = _platform_call(lambda: device_login(client, show=show, open_browser=not no_browser))
    try:
        KeyringStore().set(target, credential)
    except KeychainUnavailable as exc:
        # Don't leave a token behind that nothing can use.
        if credential.token_id:
            try:
                PlatformClient(target, credential.token).delete(f"/me/tokens/{credential.token_id}")
            except PlatformError:
                pass
        _fail(str(exc))
    me = _platform_call(lambda: PlatformClient(target, credential.token).get("/me"))
    typer.secho(f"Signed in to {target} as {me['email']}", fg=typer.colors.GREEN)


@app.command()
def logout(url: str | None = ApiUrlOpt):
    """Sign out: revoke this machine's token on the platform and remove it from the keychain."""
    target = api_url(url)
    store = KeyringStore()
    credential = store.get(target)
    if credential is None:
        typer.echo(f"Not signed in to {target}.")
        return
    if credential.token_id:
        try:
            PlatformClient(target, credential.token).delete(f"/me/tokens/{credential.token_id}")
        except PlatformError as exc:
            typer.secho(f"Couldn't revoke the token on the server ({exc}); removing it locally.", fg=typer.colors.YELLOW)
    store.delete(target)
    typer.echo(f"Signed out of {target}.")


@app.command()
def whoami(url: str | None = ApiUrlOpt):
    """Who you're signed in as, and your workspaces."""
    client = _platform_call(lambda: PlatformClient.signed_in(url))
    me = _platform_call(lambda: client.get("/me"))
    typer.echo(f"{me['display_name']} <{me['email']}> on {client.url}")
    for ws in _platform_call(lambda: client.get("/workspaces")):
        typer.echo(f"  {ws['slug']:30} {ws['role']:7} {ws['name']}")


@app.command()
def link(
    path: str = typer.Argument(".", help="Repo root to link."),
    workspace: str = typer.Option(..., "--workspace", "-w", help="Workspace slug, name, or ID."),
    project_key: str = typer.Option(..., "--project", "-p", help="Project key, e.g. KUN."),
    url: str | None = ApiUrlOpt,
):
    """Link a repo to a platform project and pull its .pmagent/ (kept out of git)."""
    root = os.path.abspath(path)
    client = _platform_call(lambda: PlatformClient.signed_in(url))
    ws = _platform_call(lambda: find_workspace(client, workspace))
    project = _platform_call(lambda: find_project(client, ws["id"], project_key))
    config = ProjectConfig(name=project["name"], description=project["description"], root_dir=root,
                           model=project["model"])
    os.makedirs(config.pmagent_dir, exist_ok=True)
    config.save()  # local engine commands (brief, chat) still work on the mirror
    state = LinkState.load(config.pmagent_dir)
    if state is None or state.project_id != project["id"]:
        state = LinkState(api_url=client.url, workspace_id=ws["id"], project_id=project["id"],
                          project_key=project["key"], project_name=project["name"])
    registry.register(project["name"], root)
    typer.echo(f"Linked {root} to {project['key']} ({project['name']}) in {ws['name']}")
    _echo_pull(_platform_call(lambda: pull(client, state, config.pmagent_dir)))
    _echo_protection(git_protect(root, config.pmagent_dir))


@app.command("pull")
def pull_cmd(
    project: str = ProjectOpt,
    force: bool = typer.Option(False, "--force", help="Overwrite local edits with the platform's versions."),
):
    """Update the local .pmagent/ mirror from the platform (only what changed)."""
    config, state, client = _linked(project)
    _echo_pull(_platform_call(lambda: pull(client, state, config.pmagent_dir, force=force)))
    git_protect(config.root_dir, config.pmagent_dir)


def _issue_row(i: dict) -> str:
    who = i.get("assignee_agent") or ("person" if i.get("assignee_user_id") else "-")
    return f"{i['key']:9} {i['type']:8} {i['status']:11} {i['priority']:7} {who:12} {i['title']}"


def _issue_detail(i: dict) -> str:
    lines = [f"{i['key']}: {i['title']}", f"  {i['type']}, {i['status']}, {i['priority']} priority"
             + (f", parent {i['parent_key']}" if i.get("parent_key") else "")]
    if i.get("depends_on"):
        lines.append(f"  depends on: {', '.join(i['depends_on'])}")
    lines += ["", i.get("description") or "(no description)", "", "Log:"]
    for e in i.get("log", []):
        who = e.get("author_agent") or "person"
        lines.append(f"  {e['created_at'][:16]} {who} {e['kind']}: {e.get('body') or e.get('changes') or ''}")
    return "\n".join(lines)


def _board(project: str, agent: str | None) -> PlatformBoard:
    _, state, client = _linked(project)
    return _platform_call(lambda: PlatformBoard(client, state, agent))


def _emit_issue(issue: dict, as_json: bool) -> None:
    typer.echo(json.dumps(issue, indent=2) if as_json else _issue_detail(issue))


@issue_app.command("list")
def issue_list(
    status: str | None = typer.Option(None, "--status"),
    mine: bool = typer.Option(False, "--mine", help="Assigned to the --as agent."),
    ready: bool = typer.Option(False, "--ready", help="Only issues that could start now."),
    agent: str | None = AsAgentOpt,
    as_json: bool = typer.Option(False, "--json"),
    project: str = ProjectOpt,
):
    """Issues by priority (urgent first), then due date."""
    board = _board(project, agent)
    issues = _platform_call(lambda: board.list(status=status, mine=mine, ready=ready))
    if as_json:
        typer.echo(json.dumps(issues, indent=2))
    elif not issues:
        typer.echo("No matching issues.")
    else:
        for i in issues:
            typer.echo(_issue_row(i))


@issue_app.command("show")
def issue_show(key: str, as_json: bool = typer.Option(False, "--json"), project: str = ProjectOpt):
    """One issue with its description, dependencies, and log."""
    board = _board(project, None)
    _emit_issue(_platform_call(lambda: board.get(key)), as_json)


@issue_app.command("next")
def issue_next(agent: str | None = AsAgentOpt, as_json: bool = typer.Option(False, "--json"),
               project: str = ProjectOpt):
    """What to work on: your (or the agent's) in-progress issue first, else the best ready one."""
    board = _board(project, agent)
    _emit_issue(_platform_call(board.next), as_json)


@issue_app.command("claim")
def issue_claim(key: str | None = typer.Argument(None, help="Omit to claim the next ready issue."),
                agent: str | None = AsAgentOpt, as_json: bool = typer.Option(False, "--json"),
                project: str = ProjectOpt):
    """Take a ready issue and start it (in_progress). Two claimers never get the same issue."""
    board = _board(project, agent)
    _emit_issue(_platform_call(lambda: board.claim(key)), as_json)


@issue_app.command("comment")
def issue_comment(key: str, text: str, agent: str | None = AsAgentOpt, project: str = ProjectOpt):
    """Add a comment to an issue's log."""
    board = _board(project, agent)
    _platform_call(lambda: board.comment(key, text))
    typer.echo(f"Commented on {key.upper()}.")


@issue_app.command("block")
def issue_block(key: str, reason: str, agent: str | None = AsAgentOpt, project: str = ProjectOpt):
    """Mark an issue blocked, with why."""
    board = _board(project, agent)
    _platform_call(lambda: board.block(key, reason))
    typer.echo(f"{key.upper()} is blocked.")


@issue_app.command("review")
def issue_review(key: str, summary: str, pr: str | None = typer.Option(None, "--pr", help="Pull request URL."),
                 agent: str | None = AsAgentOpt, project: str = ProjectOpt):
    """Hand an issue back for review: what changed, and how to test it."""
    board = _board(project, agent)
    _platform_call(lambda: board.review(key, summary, pr))
    typer.echo(f"{key.upper()} is ready for review.")


@issue_app.command("done")
def issue_done(key: str, note: str | None = typer.Option(None, "--note"), project: str = ProjectOpt):
    """Close an issue. Only a person can; coding agents stop at review."""
    board = _board(project, None)
    _platform_call(lambda: board.done(key, note))
    typer.echo(f"{key.upper()} is done.")





if __name__ == "__main__":
    app()
