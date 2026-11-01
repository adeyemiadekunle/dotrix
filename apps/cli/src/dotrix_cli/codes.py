"""`dotrix codes`: Kai's coding sessions on the platform, as the web app's Codes page shows them.

List them, show a session's turns (the request, what Kai did folded into one line, its summary,
the files it changed, the pull request and its checks), follow up with another turn, decide a
turn that waits (approve or reject it to start; accept or discard its changes), stop, revert,
recover, and wait for a turn to settle. A session is named by its issue key (its latest
session) or the start of its id.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

import typer

from .platform import PlatformClient, PlatformError
from .sync import LinkState

codes_app = typer.Typer(
    help="Kai's coding sessions: list, show, follow up, approve, accept, stop, revert, recover.",
    invoke_without_command=True,
    no_args_is_help=False,
)

CODING_STATUS = {
    "awaiting_approval": "Waiting for approval",
    "queued": "Queued",
    "running": "Working",
    "changes_ready": "Changes ready",
    "pr_opened": "PR opened",
    "no_changes": "No changes",
    "failed": "Failed",
    "recovery_required": "Needs recovery",
    "stopped": "Stopped",
    "rejected": "Rejected",
}
_COLOURS = {
    "awaiting_approval": typer.colors.YELLOW,
    "changes_ready": typer.colors.YELLOW,
    "recovery_required": typer.colors.RED,
    "failed": typer.colors.RED,
    "running": typer.colors.CYAN,
    "queued": typer.colors.CYAN,
    "pr_opened": typer.colors.GREEN,
}
WORKING = ("queued", "running")
_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9]*-\d+$")

# Waiting between polls (tests replace it).
sleep: Callable[[float], None] = time.sleep

ProjectOpt = typer.Option(".", "--project", "-p", help="Path to the linked repo")
ApprovalsOpt = typer.Option(None, "--approvals", help="Approval mode for the turn: manual, accept-edits or auto")


def status_label(status: str | None) -> str:
    return CODING_STATUS.get(status or "", (status or "").replace("_", " "))


def steps_summary(events: list[dict]) -> str:
    """What a turn did in one line, as Codes folds it: "Read 2 files, ran 1 command, edited 3 files"."""
    read = edited = ran = other = 0
    for event in events:
        if event.get("kind") != "tool":
            continue
        text = event.get("text") or ""
        if re.match(r"Read\b", text):
            read += 1
        elif re.match(r"(Edited|Wrote|Created|Deleted)\b", text):
            edited += 1
        elif re.match(r"Ran\b", text):
            ran += 1
        else:
            other += 1

    def n(count: int, verb: str, noun: str) -> str:
        return f"{verb} {count} {noun}{'s' if count > 1 else ''}" if count else ""

    parts = [n(read, "read", "file"), n(ran, "ran", "command"), n(edited, "edited", "file"), n(other, "used", "other tool")]
    line = ", ".join(p for p in parts if p)
    return line[0].upper() + line[1:] if line else "Worked on it"


class Codes:
    """The coding API for one linked project."""

    def __init__(self, client: PlatformClient, state: LinkState) -> None:
        self.client, self.state = client, state
        self.workspace = f"/workspaces/{state.workspace_id}/coding"
        self.project = f"/workspaces/{state.workspace_id}/projects/{state.project_id}/coding"

    def sessions(self, archived: str = "exclude") -> list[dict]:
        """This project's sessions, latest first."""
        rows = self.client.get(f"{self.workspace}/sessions", params={"archived": archived})
        mine = [s for s in rows if s.get("project_id") == self.state.project_id]
        return sorted(mine, key=lambda s: s.get("updated_at") or "", reverse=True)

    def find(self, target: str) -> dict:
        """A session by issue key (its latest) or the start of its id."""
        target = target.strip()
        sessions = self.sessions("include")
        if _KEY.match(target):
            found = [s for s in sessions if s["issue_key"].upper() == target.upper()]
            if not found:
                raise PlatformError(404, "not_found", f"Kai has no session on {target.upper()} in {self.state.project_key}.")
            return found[0]
        found = [s for s in sessions if s["session_id"].startswith(target.lower())]
        if len(found) != 1:
            why = "No session starts with" if not found else "More than one session starts with"
            raise PlatformError(404, "not_found", f"{why} {target}: use more of its id, or its issue key.")
        return found[0]

    def turns(self, session_id: str) -> list[dict]:
        return sorted(self.client.get(f"{self.project}/sessions/{session_id}"), key=lambda t: t["turn"])

    def run(self, run_id: str) -> dict:
        return self.client.get(f"{self.project}/runs/{run_id}")

    def diff(self, run_id: str) -> str:
        return self.client.get(f"{self.project}/runs/{run_id}/diff").get("diff") or ""

    def decide(self, run_id: str, decision: str, reason: str | None = None) -> dict:
        return self.client.post(f"{self.project}/runs/{run_id}/decision", {"decision": decision, "reason": reason})

    def stop(self, run_id: str) -> dict:
        return self.client.post(f"{self.project}/runs/{run_id}/stop")

    def revert(self, run_id: str, approval_mode: str | None) -> dict:
        return self.client.post(f"{self.project}/runs/{run_id}/revert", {"approval_mode": approval_mode})

    def recover(self, run_id: str, action: str) -> dict:
        return self.client.post(f"{self.project}/runs/{run_id}/recover", {"action": action})

    def follow_up(self, session_id: str, message: str, approval_mode: str | None) -> dict:
        body: dict[str, Any] = {"message": message}
        if approval_mode:
            body["approval_mode"] = approval_mode
        return self.client.post(f"{self.project}/sessions/{session_id}/turns", body)


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------
def _status(status: str | None) -> str:
    return typer.style(status_label(status), fg=_COLOURS.get(status or ""))


def _files(turn: dict) -> list[tuple[str, int, int]]:
    return [(str(f.get("path", "")), int(f.get("added") or 0), int(f.get("removed") or 0)) for f in turn.get("files_changed") or []]


def _lines(added: int, removed: int) -> str:
    return typer.style(f"+{added}", fg=typer.colors.GREEN) + " " + typer.style(f"−{removed}", fg=typer.colors.RED)


def echo_session_row(session: dict, ago: Callable[[str | None], str]) -> None:
    title = (session.get("title") or session.get("issue_title") or "").strip()
    title = title.splitlines()[0][:60] if title else ""
    pr = f"  PR #{session['pr_number']}" + (f" ({session['pr_state']})" if session.get("pr_state") else "") if session.get("pr_number") else ""
    branch = f"  {session['branch']}" if session.get("branch") else ""
    marks = ("  · from a conversation" if session.get("thread_id") else "") + ("  · archived" if session.get("archived") else "")
    typer.echo(
        f"{session['issue_key']:<10} {session['session_id'][:8]}  {_status(session.get('status'))}  {title}"
        + typer.style(f"{branch}{pr}  {ago(session.get('updated_at'))}{marks}", dim=True)
    )


def echo_turn(turn: dict, *, steps: bool = False) -> None:
    where = "your computer" if turn.get("location") == "local" else "cloud"
    head = f"Turn {turn['turn']}"
    if turn.get("revert_of"):
        head += " (a revert)"
    typer.secho(f"\n{head}  ", bold=True, nl=False)
    typer.echo(_status(turn.get("status")) + typer.style(f"  · {where}", dim=True))
    request = (turn.get("note") or "").strip()
    if request:
        typer.echo(f"  You: {request}")
    events = turn.get("events") or []
    if any(e.get("kind") == "tool" for e in events):
        typer.secho(f"  {steps_summary(events)}", dim=True)
        if steps:
            for event in events:
                if event.get("kind") in ("tool", "error"):
                    typer.secho(f"    · {event['text']}", fg=typer.colors.RED if event["kind"] == "error" else None, dim=event["kind"] != "error")
    if turn.get("summary"):
        typer.echo("")
        for line in turn["summary"].strip().splitlines():
            typer.echo(f"  {line}")
    if turn.get("error"):
        typer.secho(f"  {turn['error']}", fg=typer.colors.RED)
    files = _files(turn)
    if files:
        added, removed = sum(f[1] for f in files), sum(f[2] for f in files)
        typer.echo(f"\n  {len(files)} file{'s' if len(files) > 1 else ''} changed  {_lines(added, removed)}")
        for path, a, r in files:
            typer.echo(f"    {path}  {_lines(a, r)}")
    if turn.get("ci_sensitive"):
        typer.secho(f"  Changes files CI runs, so they wait for a person: {', '.join(turn['ci_sensitive'])}", fg=typer.colors.YELLOW)
    hint = _hint(turn)
    if hint:
        typer.secho(f"  {hint}", fg=typer.colors.CYAN)


def _hint(turn: dict) -> str:
    key = turn["issue_key"]
    status = turn.get("status")
    if status == "awaiting_approval" and turn.get("can_decide"):
        return f"dotrix codes approve {key}  or  dotrix codes reject {key}"
    if status == "changes_ready" and turn.get("can_decide"):
        return f"dotrix codes accept {key}  or  dotrix codes discard {key}"
    if status == "recovery_required" and turn.get("can_recover"):
        return f"dotrix codes recover {key}  (or --discard)"
    if status in WORKING:
        return f"dotrix codes wait {key}  ·  dotrix codes stop {key}"
    return ""


def echo_session(session: dict, turns: list[dict], *, steps: bool = False) -> None:
    title = session.get("title") or session.get("issue_title") or ""
    typer.secho(f"{session['issue_key']}  {title}", bold=True)
    latest = turns[-1] if turns else {}
    meta = [f"session {session['session_id'][:8]}", _status(session.get("status"))]
    if latest.get("repo_full_name"):
        meta.append(latest["repo_full_name"])
    if session.get("branch"):
        meta.append(session["branch"])
    if latest.get("model"):
        meta.append(latest["model"].split(":")[-1])
    if session.get("thread_id"):
        meta.append("from a conversation")
    typer.echo("  ".join(meta))
    for turn in turns:
        echo_turn(turn, steps=steps)
    if session.get("pr_number"):
        pushed = next((t for t in reversed(turns) if t.get("commit_sha") and t.get("pr_number")), {})
        ci = pushed.get("ci_state")
        checks = {"passed": typer.style("CI passed", fg=typer.colors.GREEN), "failed": typer.style("CI failed", fg=typer.colors.RED)}.get(ci or "", "checks pending")
        state = f" ({session['pr_state']})" if session.get("pr_state") else ""
        typer.echo(f"\nPull request #{session['pr_number']}{state}  {checks}  {session.get('pr_url') or ''}".rstrip())
        if pushed.get("review_posted_url"):
            typer.echo(f"Juno's review: {pushed['review_posted_url']}")


def echo_diff(diff: str) -> None:
    if not diff.strip():
        typer.secho("  (no changes yet)", dim=True)
        return
    for line in diff.splitlines():
        colour = None
        if line.startswith("+") and not line.startswith("+++"):
            colour = typer.colors.GREEN
        elif line.startswith("-") and not line.startswith("---"):
            colour = typer.colors.RED
        elif line.startswith("@@"):
            colour = typer.colors.CYAN
        typer.secho(line, fg=colour, bold=line.startswith("diff --git"))


def wait_for(codes: Codes, run: dict, *, interval: float = 2.0) -> dict:
    """Print a turn's steps as they come until it stops working; returns the turn."""
    shown = 0
    while True:
        events = run.get("events") or []
        if len(events) < shown:  # the run keeps its latest 300: start again from what's there
            shown = 0
        for event in events[shown:]:
            if event.get("kind") in ("tool", "step"):
                typer.secho(f"· {event['text']}", dim=True)
            elif event.get("kind") == "error":
                typer.secho(f"· {event['text']}", fg=typer.colors.RED)
        shown = len(events)
        if run.get("status") not in WORKING:
            return run
        sleep(interval)
        run = codes.run(run["id"])


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def _ctx(project: str) -> tuple[Codes, Any]:
    """The project's coding API, and the CLI module (for its helpers)."""
    from . import cli

    _, state, client = cli._linked(project)
    return Codes(client, state), cli


def _approval(cli: Any, value: str | None) -> str | None:
    if value is None:
        return None
    mode = cli._approval_mode(value)
    if mode is None:
        raise typer.BadParameter("use manual, accept-edits or auto", param_hint="--approvals")
    return mode


def _latest(cli: Any, codes: Codes, target: str) -> tuple[dict, list[dict]]:
    session = cli._platform_call(lambda: codes.find(target))
    turns = cli._platform_call(lambda: codes.turns(session["session_id"]))
    if not turns:
        cli._fail(f"{session['issue_key']}'s session has no turns.")
    return session, turns


@codes_app.callback()
def codes_list(
    ctx: typer.Context,
    project: str = ProjectOpt,
    include_archived: bool = typer.Option(False, "--all", help="Include archived sessions"),
):
    """List Kai's coding sessions in this project, latest first."""
    if ctx.invoked_subcommand is not None:
        return
    codes, cli = _ctx(project)
    sessions = cli._platform_call(lambda: codes.sessions("include" if include_archived else "exclude"))
    if not sessions:
        typer.echo("Kai has no coding sessions here yet. Start one with `dotrix code KEY`, or in Build mode in `dotrix chat`.")
        return
    for session in sessions:
        echo_session_row(session, cli._ago)


@codes_app.command("show")
def codes_show(
    target: str = typer.Argument(..., help="An issue key (its latest session) or the start of a session's id"),
    diff: bool = typer.Option(False, "--diff", help="Also print the latest turn's diff"),
    steps: bool = typer.Option(False, "--steps", help="List every step, not just the one-line summary"),
    project: str = ProjectOpt,
):
    """A session's turns: your requests, what Kai did, its summaries, the files changed, the PR and its checks."""
    codes, cli = _ctx(project)
    session, turns = _latest(cli, codes, target)
    echo_session(session, turns, steps=steps)
    if diff:
        typer.echo("")
        echo_diff(cli._platform_call(lambda: codes.diff(turns[-1]["id"])))


@codes_app.command("follow")
def codes_follow(
    target: str = typer.Argument(..., help="An issue key or the start of a session's id"),
    message: str = typer.Argument(..., help="What Kai should do in this turn"),
    approvals: str | None = ApprovalsOpt,
    wait: bool = typer.Option(False, "--wait", help="Wait here for the turn, printing its steps"),
    project: str = ProjectOpt,
):
    """Ask Kai for another turn in a session."""
    codes, cli = _ctx(project)
    mode = _approval(cli, approvals)
    session = cli._platform_call(lambda: codes.find(target))
    run = cli._platform_call(lambda: codes.follow_up(session["session_id"], message, mode))
    _started(cli, codes, run, wait)


def _started(cli: Any, codes: Codes, run: dict, wait: bool) -> None:
    key = run["issue_key"]
    if run["status"] == "awaiting_approval":
        typer.echo(f"{key}: turn {run['turn']} waits for an approval (dotrix codes approve {key}).")
        return
    typer.echo(f"{key}: turn {run['turn']} is {status_label(run['status']).lower()}.")
    if wait:
        _wait(cli, codes, run)


def _wait(cli: Any, codes: Codes, run: dict) -> None:
    try:
        run = cli._platform_call(lambda: wait_for(codes, run))
    except KeyboardInterrupt:
        typer.secho(f"\nStopped waiting; Kai keeps working (dotrix codes stop {run['issue_key']} stops it).", dim=True)
        return
    echo_turn(run)


@codes_app.command("wait")
def codes_wait(
    target: str = typer.Argument(..., help="An issue key or the start of a session's id"),
    project: str = ProjectOpt,
):
    """Wait for a session's latest turn to stop working, printing its steps."""
    codes, cli = _ctx(project)
    _, turns = _latest(cli, codes, target)
    _wait(cli, codes, turns[-1])


def _waiting(cli: Any, turns: list[dict], status: str, what: str) -> dict:
    turn = next((t for t in reversed(turns) if t.get("status") == status), None)
    if turn is None:
        cli._fail(f"No turn {what} (the latest is {status_label(turns[-1].get('status')).lower()}).")
    return turn


@codes_app.command("approve")
def codes_approve(target: str = typer.Argument(...), project: str = ProjectOpt):
    """Approve a turn that waits to start."""
    codes, cli = _ctx(project)
    _, turns = _latest(cli, codes, target)
    turn = _waiting(cli, turns, "awaiting_approval", "waits for an approval")
    run = cli._platform_call(lambda: codes.decide(turn["id"], "approve"))
    typer.echo(f"Approved turn {run['turn']}: {status_label(run['status']).lower()}.")


@codes_app.command("reject")
def codes_reject(
    target: str = typer.Argument(...),
    reason: str | None = typer.Option(None, "--reason", help="Why, for Kai and the audit log"),
    project: str = ProjectOpt,
):
    """Reject a turn that waits to start."""
    codes, cli = _ctx(project)
    _, turns = _latest(cli, codes, target)
    turn = _waiting(cli, turns, "awaiting_approval", "waits for an approval")
    cli._platform_call(lambda: codes.decide(turn["id"], "reject", reason))
    typer.echo(f"Rejected turn {turn['turn']}.")


@codes_app.command("accept")
def codes_accept(target: str = typer.Argument(...), project: str = ProjectOpt):
    """Accept a turn's changes and push them (Manual approval mode)."""
    codes, cli = _ctx(project)
    _, turns = _latest(cli, codes, target)
    turn = _waiting(cli, turns, "changes_ready", "has changes ready")
    run = cli._platform_call(lambda: codes.decide(turn["id"], "approve"))
    typer.echo(f"Accepted turn {run['turn']}'s changes: {status_label(run['status']).lower()}.")


@codes_app.command("discard")
def codes_discard(
    target: str = typer.Argument(...),
    reason: str | None = typer.Option(None, "--reason"),
    project: str = ProjectOpt,
):
    """Discard a turn's changes instead of pushing them."""
    codes, cli = _ctx(project)
    _, turns = _latest(cli, codes, target)
    turn = _waiting(cli, turns, "changes_ready", "has changes ready")
    if not turn.get("can_decide") and turn.get("can_stop"):
        cli._platform_call(lambda: codes.stop(turn["id"]))
    else:
        cli._platform_call(lambda: codes.decide(turn["id"], "reject", reason))
    typer.echo(f"Discarded turn {turn['turn']}'s changes.")


@codes_app.command("stop")
def codes_stop(target: str = typer.Argument(...), project: str = ProjectOpt):
    """Stop the turn Kai is on (or one that waits)."""
    codes, cli = _ctx(project)
    _, turns = _latest(cli, codes, target)
    turn = next((t for t in reversed(turns) if t.get("can_stop")), None)
    if turn is None:
        cli._fail("Nothing to stop: no turn is working or waiting.")
    run = cli._platform_call(lambda: codes.stop(turn["id"]))
    typer.echo(f"Turn {turn['turn']}: {status_label(run['status']).lower()}.")


@codes_app.command("revert")
def codes_revert(
    target: str = typer.Argument(...),
    turn_number: int | None = typer.Option(None, "--turn", help="The turn to revert (default: the latest you can)"),
    approvals: str | None = ApprovalsOpt,
    project: str = ProjectOpt,
):
    """Revert a pushed turn on the session's branch, as a new turn."""
    codes, cli = _ctx(project)
    mode = _approval(cli, approvals)
    _, turns = _latest(cli, codes, target)
    if turn_number is not None:
        turn = next((t for t in turns if t["turn"] == turn_number), None)
        if turn is None:
            cli._fail(f"The session has no turn {turn_number}.")
        if not turn.get("can_revert"):
            cli._fail(f"Turn {turn_number} can't be reverted (only pushed turns whose PR is open).")
    else:
        turn = next((t for t in reversed(turns) if t.get("can_revert")), None)
        if turn is None:
            cli._fail("No turn to revert: only pushed turns whose PR is open.")
    run = cli._platform_call(lambda: codes.revert(turn["id"], mode))
    typer.echo(f"Turn {run['turn']} reverts turn {turn['turn']}: {status_label(run['status']).lower()}.")


@codes_app.command("recover")
def codes_recover(
    target: str = typer.Argument(...),
    discard: bool = typer.Option(False, "--discard", help="Give the turn up instead of checking GitHub"),
    project: str = ProjectOpt,
):
    """Settle a turn whose outcome is uncertain: check what GitHub shows, or discard it."""
    codes, cli = _ctx(project)
    _, turns = _latest(cli, codes, target)
    turn = _waiting(cli, turns, "recovery_required", "needs recovery")
    run = cli._platform_call(lambda: codes.recover(turn["id"], "discard" if discard else "check"))
    typer.echo(f"Turn {run['turn']}: {status_label(run['status']).lower()}.")
