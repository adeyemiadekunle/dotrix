"""`dotrix runner`: this computer codes your local turns, in a worktree of your checkout.

The platform keeps the run (approvals, events, the outcome) and pushes what's accepted itself; this
only ever hands back a patch. So it holds no GitHub token and no provider key from the platform: the
coding tool runs with whatever is signed in on this machine (Claude Code's login, OpenCode's
config).

Each turn gets a worktree of its own outside the checkout (`~/.dotrix/worktrees/...`), on the
session's branch or the base branch as the remote has it, so your working copy and its changes are
never touched. A worktree separates directories, it isn't a security boundary, and nothing isolates
the tool for now: so it only edits files (Claude Code's acceptEdits, no commands), with an
environment that carries its own provider's settings and none of this machine's other credentials
(`dotrix_cli.toolenv`). A worktree is kept after its turn, for a while: its patch is already on the
platform, so the runner removes worktrees untouched for `WORKTREE_DAYS` days (never the one it's
coding in) when it starts and after each turn.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform as platform_info
import shlex
import shutil
import signal
import socket
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .toolenv import tool_environment

TOOLS = ("claude-code", "opencode")
EVENTS_PER_BEAT = 50
WORKTREE_DAYS = 3  # a finished turn's worktree is removed once untouched this long
EVENTS_SECONDS = 2.0  # waiting events go out this often (the lease is renewed every third of it regardless)
STOP_GRACE_SECONDS = 5


class Api(Protocol):
    """The platform calls the runner makes (the CLI's client, or a test's)."""

    async def post(self, path: str, body: Any = None) -> Any: ...


class LeaseLost(Exception):
    """The platform no longer gives this runner the turn: stop writing, keep the worktree."""


@dataclass
class Tool:
    """How to run a coding tool headless here: its command (the brief goes on stdin)."""

    name: str  # "claude-code", "opencode", or what --command stands in for
    argv: list[str]

    @classmethod
    def named(cls, name: str) -> Tool:
        if name == "claude-code":
            # Not isolated, so it may only edit files: no commands on this machine.
            return cls(name, ["claude", "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits"])
        if name == "opencode":
            return cls(name, ["opencode", "run", "--format", "json"])
        raise ValueError(f"Unknown coding tool {name!r} (one of {', '.join(TOOLS)})")


def found_tools() -> list[str]:
    """The coding tools on this machine's PATH, preferred first."""
    return [name for name, binary in (("claude-code", "claude"), ("opencode", "opencode")) if shutil.which(binary)]


@dataclass
class Outcome:
    events: list[dict[str, str]] = field(default_factory=list)
    summary: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    root: Path | None = None  # the worktree: paths the tool names are shown relative to it
    commands: set[str] = field(default_factory=set)  # tool calls that ran a command (their result is its output)


MAX_STEP = 160
MAX_OUTPUT = 8_000  # of a command's output: its start and, mostly, its end (where errors are)


def output_event(text: str, ref: str | None, *, failed: bool) -> dict[str, str]:
    """A command's output as the session's Terminal shows it (as a cloud turn's, `coding/tools.py`)."""
    text = text.rstrip()
    if len(text) > MAX_OUTPUT:
        text = text[:1_500] + f"\n… ({len(text) - MAX_OUTPUT:,} characters left out) …\n" + text[-(MAX_OUTPUT - 1_500):]
    return {"kind": "output-error" if failed else "output", "text": text, **({"ref": ref} if ref else {})}


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(c.get("text", "")) for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def _clip(text: str, limit: int = MAX_STEP) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _relative(path: str, root: Path | None) -> str:
    """A path the tool named, relative to the worktree when it's inside it (as a cloud turn shows them)."""
    if root is not None and path and Path(path).is_absolute():
        try:
            return Path(path).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return path
    return path.removeprefix("./")


def describe(tool: str, args: dict[str, Any], root: Path | None = None) -> str | None:
    """What a tool call did, in the words a cloud turn's events use (`coding/tools.py`): the app's
    Terminal panel lists the `Ran …` ones, so local and cloud turns read the same."""
    path = _relative(str(args.get("file_path") or args.get("path") or ""), root)
    match tool:
        case "Bash" | "shell" | "bash":
            return f"Ran {_clip(str(args.get('command', '')))}"
        case "Edit" | "MultiEdit" | "edit":
            return f"Edited {path}"
        case "Write" | "write":
            return f"Wrote {path}"
        case "Read" | "read":
            return f"Read {path}"
        case "Glob" | "Grep" | "glob" | "grep":
            return f"Searched for {_clip(str(args.get('pattern', '')), 80)}"
        case "execute":
            return "Ran a script"
        case "subagent":
            return f"Asked a subagent to {_clip(str(args.get('description', '')), 120)}"
        case "TodoWrite" | "skill":
            return None
        case _:
            return f"Used {tool}"


def parse_line(line: str, out: Outcome) -> None:
    """One line of the tool's output as events: Claude Code's stream-json, OpenCode's JSON, or text."""
    line = line.strip()
    if not line:
        return
    try:
        event = json.loads(line)
    except ValueError:
        out.events.append({"kind": "text", "text": line[:4000]})
        return
    if not isinstance(event, dict):
        return
    kind = event.get("type")
    if kind == "assistant":  # Claude Code
        for item in (event.get("message") or {}).get("content") or []:
            if item.get("type") == "text" and item.get("text"):
                out.events.append({"kind": "text", "text": item["text"][:4000]})
            elif item.get("type") == "tool_use":
                ref = str(item.get("id") or "") if item.get("name") == "Bash" else ""
                if ref:
                    out.commands.add(ref)
                if said := describe(str(item.get("name")), item.get("input") or {}, out.root):
                    out.events.append({"kind": "tool", "text": said, **({"ref": ref} if ref else {})})
    elif kind == "user":  # Claude Code's tool results: a command's output is kept
        for item in (event.get("message") or {}).get("content") or []:
            if isinstance(item, dict) and item.get("type") == "tool_result" and item.get("tool_use_id") in out.commands:
                out.events.append(output_event(_result_text(item.get("content")), item["tool_use_id"],
                                               failed=bool(item.get("is_error"))))
    elif kind == "result":  # Claude Code's last event
        out.summary = event.get("result") or out.summary
        usage = event.get("usage") or {}
        out.usage = {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                     "cost_usd": event.get("total_cost_usd")}
        if event.get("is_error") or event.get("subtype", "success") != "success":
            out.events.append({"kind": "error", "text": str(event.get("result") or event.get("subtype"))[:4000]})
    elif kind == "text":  # OpenCode
        text = (event.get("part") or {}).get("text")
        if text:
            out.events.append({"kind": "text", "text": text[:4000]})
            out.summary = text
    elif kind == "tool_use":  # OpenCode
        part = event.get("part") or {}
        state = part.get("state") or {}
        command = part.get("tool") in ("shell", "bash")
        ref = str(part.get("callID") or part.get("id") or "") if command else ""
        if said := describe(str(part.get("tool")), state.get("input") or {}, out.root):
            out.events.append({"kind": "tool", "text": said, **({"ref": ref} if ref else {})})
        if command and state.get("status") in ("completed", "error") and (state.get("output") or state.get("error")):
            failed = state.get("status") == "error" or (state.get("metadata") or {}).get("exit") not in (0, None)
            out.events.append(output_event(str(state.get("output") or state.get("error")), ref or None, failed=failed))
    elif kind == "error":
        error = event.get("error") or {}
        out.events.append({"kind": "error", "text": str(error.get("message") or error)[:4000]})


async def git(cwd: Path, *args: str, check: bool = True) -> str:
    process = await asyncio.create_subprocess_exec(
        "git", "-c", "core.quotepath=off", "-c", "core.autocrlf=false", *args, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await process.communicate()
    if check and process.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: {err.decode(errors='replace').strip()[:500]}")
    return out.decode(errors="replace")


@dataclass
class LocalRunner:
    api: Api
    repo: Path  # the person's checkout (its .git is shared by the worktrees)
    workspace_id: str
    project_id: str
    tool: str | None = None  # None: the first one found here
    command: str | None = None  # instead of a known tool: any command (brief on stdin, output as events)
    worktrees: Path = field(default_factory=lambda: Path.home() / ".dotrix" / "worktrees")
    # This checkout's name on the platform. One registration per checkout: two runners on one computer
    # (for two projects) never share one, so neither claims the other's turns.
    name: str = ""
    remote: str = "origin"
    echo: Callable[[str], None] = print
    # What happens, for a program running this one (the desktop app, `--json`): a dict per event.
    notify: Callable[[dict[str, Any]], None] = lambda event: None
    runner_id: str | None = None
    beat_seconds: float | None = None  # between heartbeats while the tool works (default: a third of the lease)
    # What the agent did reaches the platform this soon (a heartbeat as soon as events wait this long),
    # so the turn's view in the app keeps up as it does for a cloud turn.
    events_seconds: float = EVENTS_SECONDS
    keep_days: float = WORKTREE_DAYS
    _coding_in: Path | None = None  # the worktree of the turn in progress, never cleaned

    def tools(self) -> list[str]:
        if self.tool:
            return [self.tool]
        found = found_tools()
        return found or ([] if self.command is None else ["claude-code"])

    @property
    def base(self) -> str:
        return f"/workspaces/{self.workspace_id}/coding/runners"

    def __post_init__(self) -> None:
        if not self.name:
            where = hashlib.sha256(str(self.repo.resolve()).encode()).hexdigest()[:6]
            self.name = f"{socket.gethostname()} · {self.repo.name} ({where})"[:100]

    async def register(self) -> dict[str, Any]:
        tools = self.tools()
        if not tools:
            raise RuntimeError("No coding tool here: install Claude Code (`claude`) or OpenCode (`opencode`)")
        runner = await self.api.post(self.base, {
            "name": self.name[:100], "platform": platform_info.system().lower(), "tools": tools,
            "isolation": "none", "project_ids": [self.project_id],
        })
        self.runner_id = runner["id"]
        self.notify({"event": "registered", "runner_id": runner["id"], "name": runner["name"],
                     "isolation": runner["isolation"], "tools": runner["tools"]})
        return runner

    async def once(self) -> bool:
        """Claim one turn and code it; False when none waits."""
        if self.runner_id is None:
            await self.register()
        claimed = await self.api.post(f"{self.base}/{self.runner_id}/claim")
        if not claimed.get("run"):
            return False
        try:
            await self.work(claimed["run"])
        finally:
            if self._coding_in is not None:
                try:
                    os.utime(self._coding_in)  # its age counts from when the turn ended
                except OSError:
                    pass
            self._coding_in = None
            self.notify({"event": "done", "run_id": claimed["run"]["run_id"]})
            await self.clean_worktrees()
        return True

    async def clean_worktrees(self) -> list[Path]:
        """Remove this project's worktrees untouched for `keep_days` (never the one in use); the removed."""
        folder = self.worktrees / self.project_id
        if not folder.is_dir():
            return []
        cutoff = time.time() - self.keep_days * 86400
        removed: list[Path] = []
        for tree in sorted(folder.iterdir()):
            if not tree.is_dir() or tree == self._coding_in:
                continue
            try:
                if tree.stat().st_mtime > cutoff:
                    continue
            except OSError:
                continue
            try:
                await git(self.repo, "worktree", "remove", "--force", str(tree))
            except RuntimeError:
                shutil.rmtree(tree, ignore_errors=True)  # not this checkout's (or git lost track of it)
            if not tree.exists():
                removed.append(tree)
        if removed:
            try:
                await git(self.repo, "worktree", "prune")
            except RuntimeError:
                pass
            self.echo(f"Removed {len(removed)} old worktree{'s' if len(removed) > 1 else ''}")
        return removed

    async def serve(self, *, poll_seconds: float = 5, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        await self.clean_worktrees()
        while not stop.is_set():
            try:
                if await self.once():
                    continue
            except LeaseLost:
                continue
            try:
                await asyncio.wait_for(stop.wait(), poll_seconds)
            except TimeoutError:
                pass

    async def work(self, run: dict[str, Any]) -> None:
        path = f"{self.base}/{self.runner_id}/runs/{run['run_id']}"
        token = run["lease_token"]
        beat_every = self.beat_seconds if self.beat_seconds is not None else max(5.0, run["lease_seconds"] / 3)
        pending: list[dict[str, str]] = []

        async def beat(extra: dict[str, Any] | None = None) -> bool:
            body = {"lease_token": token, "events": pending[:EVENTS_PER_BEAT], **(extra or {})}
            try:
                answer = await self.api.post(f"{path}/heartbeat", body)
            except Exception as exc:
                if _lost(exc):
                    raise LeaseLost() from exc
                return False  # the platform may be back before the lease runs out
            del pending[:EVENTS_PER_BEAT]
            return bool(answer.get("stop"))

        async def report(outcome: str, **fields: Any) -> None:
            try:
                await self.api.post(f"{path}/result", {"lease_token": token, "outcome": outcome,
                                                       "events": pending[:EVENTS_PER_BEAT], **fields})
            except Exception as exc:
                if _lost(exc):
                    raise LeaseLost() from exc
                raise

        if run["project_id"] != self.project_id:  # never code a turn against another project's checkout
            await report("failed", error="Claimed by a runner for another project's checkout; ask again")
            return
        ref = run.get("branch") or run["base_branch"]
        self.echo(f"{run['issue_key']} turn {run['turn']}: {run['title']}")
        try:
            await git(self.repo, "fetch", "-q", "--no-tags", self.remote, f"refs/heads/{ref}")
        except RuntimeError as exc:
            await report("failed", error=f"Couldn't fetch {ref} from {self.remote}: {exc}")
            return
        # A worktree per attempt: a turn claimed again (after a crash) never reuses one that may hold work.
        tree = self.worktrees / run["project_id"] / f"{run['issue_key'].lower()}-{run['run_id'][-6:]}-{token}"
        tree.parent.mkdir(parents=True, exist_ok=True)
        self._coding_in = tree
        await git(self.repo, "worktree", "add", "-q", "--detach", str(tree), "FETCH_HEAD")
        base_sha = (await git(tree, "rev-parse", "HEAD")).strip()
        pending.append({"kind": "step", "text": f"Worktree on {ref} at {base_sha[:7]} (not isolated: the tool edits files only)"})
        self.notify({"event": "turn", "run_id": run["run_id"], "issue_key": run["issue_key"], "turn": run["turn"],
                     "worktree": str(tree)})
        if await beat({"base_sha": base_sha, "worktree": str(tree)}):
            await report("stopped", base_sha=base_sha)
            return

        if self.command:
            tool = Tool("command", shlex.split(self.command))
        else:
            here = self.tools()
            tool = Tool.named(run["tool"] if run["tool"] in here else here[0])
        # A custom command stands in for the requested tool; its name is only a display label.
        environment_tool = run["tool"] if self.command else tool.name
        # The tool by its full path: on Windows `claude` and `opencode` are .cmd files, found only that way.
        argv = [shutil.which(tool.argv[0]) or tool.argv[0], *tool.argv[1:]]
        out = Outcome(root=tree)
        try:
            process = await asyncio.create_subprocess_exec(
                *argv, cwd=tree, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=_env(environment_tool), **_own_group(),
            )
        except OSError as exc:
            await report("failed", base_sha=base_sha, error=f"Couldn't start {tool.name}: {exc}")
            return
        assert process.stdin and process.stdout and process.stderr
        process.stdin.write(run["brief"].encode())
        await process.stdin.drain()
        process.stdin.close()
        errors = asyncio.create_task(process.stderr.read())
        stopped = False

        def take(line: str) -> None:
            before = len(out.events)
            parse_line(line, out)
            pending.extend(out.events[before:])

        async def read() -> None:
            assert process.stdout
            await read_lines(process.stdout, take)

        reading = asyncio.create_task(read())
        last = time.monotonic()
        try:
            while not reading.done():
                await asyncio.wait({reading}, timeout=min(1.0, beat_every, self.events_seconds))
                since = time.monotonic() - last
                if since >= beat_every or len(pending) >= EVENTS_PER_BEAT or (pending and since >= self.events_seconds):
                    last = time.monotonic()
                    if await beat():
                        stopped = True
                        await _terminate(process)
        except LeaseLost:
            await _terminate(process)
            self.echo(f"  The platform gave the turn to another attempt; left {tree} as it is")
            raise
        except (asyncio.CancelledError, KeyboardInterrupt):
            # The runner itself is stopping (Ctrl-C, or the desktop app stopping it): the tool runs in a
            # group of its own, so it would go on without anyone to report it. Stop it first.
            reading.cancel()
            await asyncio.shield(_terminate(process))
            raise
        if not reading.cancelled() and (failed := reading.exception()) is not None:
            await _terminate(process)  # its output can't be read: stop it rather than let its pipe fill
            await process.wait()
            await report("failed", base_sha=base_sha, error=f"Couldn't read {tool.name}'s output: {failed}")
            return
        code = await process.wait()
        stderr = (await errors).decode(errors="replace").strip()
        if stopped:
            await report("stopped", base_sha=base_sha, summary=out.summary)
            self.echo("  Stopped")
            return

        await git(tree, "add", "-A")
        patch = await git(tree, "diff", "--cached", "--binary", "--no-color", "--no-ext-diff", "--no-textconv",
                          "--no-renames", base_sha)
        usage = {k: v for k, v in out.usage.items() if v is not None}
        if not patch.strip():
            if code != 0:
                error = (stderr or f"{tool.name} exited with {code}")[-2000:]
                await report("failed", base_sha=base_sha, summary=out.summary, error=error, **usage)
                self.echo(f"  Failed: {_tail(error)}")
            else:
                await report("no_changes", base_sha=base_sha, summary=out.summary, **usage)
                self.echo("  No changes")
            return
        await report("changes", base_sha=base_sha, patch=patch, summary=out.summary or _tail(stderr), **usage)
        self.echo(f"  Changes reported; the worktree stays at {tree}")


MAX_LINE = 4_000_000  # longer output lines are cut here (events keep 4,000 characters of a line anyway)


async def read_lines(stream: asyncio.StreamReader, take: Callable[[str], None]) -> None:
    """Every line of the tool's output, however long: read a chunk at a time (a line over the
    stream's limit would end `readline`), each cut at MAX_LINE."""
    buffer = b""
    while chunk := await stream.read(65536):
        buffer += chunk
        while (end := buffer.find(b"\n")) >= 0:
            take(buffer[:min(end, MAX_LINE)].decode(errors="replace"))
            buffer = buffer[end + 1:]
        if len(buffer) > MAX_LINE:  # a line without an end yet: keep its start, skip the rest
            take(buffer[:MAX_LINE].decode(errors="replace"))
            while chunk := await stream.read(65536):
                if (end := chunk.find(b"\n")) >= 0:
                    buffer = chunk[end + 1:]
                    break
            else:
                buffer = b""
    if buffer:
        take(buffer.decode(errors="replace"))


def _lost(exc: Exception) -> bool:
    return getattr(exc, "code", None) == "lease_lost"


def _env(tool: str = "claude-code") -> dict[str, str]:
    """Only the selected tool's credentials and execution settings cross this boundary."""
    return tool_environment(tool, os.environ)


def _tail(text: str) -> str | None:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1][:2000] if lines else None


def _own_group() -> dict[str, Any]:
    """Start the tool in a process group of its own, so Stop reaches everything it started."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
    return {"start_new_session": True}


async def _terminate(process: asyncio.subprocess.Process) -> None:
    """Interrupt the tool (and what it started), then kill the whole tree if it doesn't end."""
    if process.returncode is not None:
        return
    try:
        if os.name == "nt":
            os.kill(process.pid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]  # its group's Ctrl-Break
        else:
            os.killpg(process.pid, signal.SIGINT)
        await asyncio.wait_for(process.wait(), STOP_GRACE_SECONDS)
    except (TimeoutError, ProcessLookupError, OSError):
        try:
            if os.name == "nt":  # every process it started, not just the first
                await asyncio.to_thread(subprocess.run, ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                        capture_output=True, check=False)
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
