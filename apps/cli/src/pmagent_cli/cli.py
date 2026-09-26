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
from typing import Optional

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

app = typer.Typer(help="Multi-agent project management for any repo (init or connect).")
task_app = typer.Typer(help="Create, list, and update tasks on the project board.")
calendar_app = typer.Typer(help="Calendar views derived from task due/scheduled dates.")
handoff_app = typer.Typer(help="Hand-off instructions for coding agents (Claude Code, Codex).")
app.add_typer(task_app, name="task")
app.add_typer(calendar_app, name="calendar")
app.add_typer(handoff_app, name="handoff")

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
            "    git rm -r --cached " + " ".join(sorted({l.split('/')[0] for l in leaks}))
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
@app.command()
def brief(project: str = ProjectOpt):
    """One-shot: ask the PM agent for a project briefing (Chat Mode, no writes expected)."""
    config = _resolve_project(project)
    agent = build_agent(config, checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    result = agent.invoke({"messages": [{"role": "user", "content": "Give me my project briefing."}]}, cfg)
    if approvals.has_pending(result):
        # A briefing shouldn't write. If it tries, refuse rather than prompt.
        result = agent.invoke(approvals.resume_command(
            result, "reject", "Briefings are read-only. Don't write anything."), cfg)
    typer.echo(result["messages"][-1].content)


@app.command()
def chat(project: str = ProjectOpt):
    """Interactive session. Any write pauses for your approval. That pause IS Action Mode.

    Safe to run alongside `pmagent run --background` jobs and coding agents on
    the same project: each gets its own thread_id, and writes are file-locked."""
    config = _resolve_project(project)
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
    message: Optional[str] = typer.Option(None, "--message", "-m", help="Reason, sent to the agent on reject."),
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
    assignee: Optional[str] = typer.Option(None, "--assignee"),
    due: Optional[str] = typer.Option(None, "--due", help="YYYY-MM-DD"),
    scheduled: Optional[str] = typer.Option(None, "--scheduled", help="YYYY-MM-DD or ISO datetime"),
    depends_on: Optional[str] = typer.Option(None, "--depends-on", help="Comma-separated task ids"),
    labels: Optional[str] = typer.Option(None, "--labels", help="Comma-separated"),
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
    status: Optional[str] = typer.Option(None, "--status"),
    assignee: Optional[str] = typer.Option(None, "--assignee"),
    label: Optional[str] = typer.Option(None, "--label"),
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
    status: Optional[str] = typer.Option(None, "--status"),
    priority: Optional[str] = typer.Option(None, "--priority"),
    assignee: Optional[str] = typer.Option(None, "--assignee"),
    due: Optional[str] = typer.Option(None, "--due"),
    scheduled: Optional[str] = typer.Option(None, "--scheduled"),
    depends_on: Optional[str] = typer.Option(None, "--depends-on"),
    labels: Optional[str] = typer.Option(None, "--labels"),
    title: Optional[str] = typer.Option(None, "--title"),
    description: Optional[str] = typer.Option(None, "--description", "-d"),
    note: Optional[str] = typer.Option(None, "--note", help="Appended to the task log."),
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
    note: Optional[str] = typer.Option(None, "--note"),
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
    out: Optional[str] = typer.Option(None, "--out", "-o", help="Default: .pmagent/calendar.ics"),
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


if __name__ == "__main__":
    app()
