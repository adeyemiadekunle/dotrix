"""`dotrix runner`: this computer codes your local turns, in a worktree of your checkout.

The platform keeps the run (approvals, events, the outcome) and pushes what's accepted itself; this
only ever hands back a patch. So it holds no GitHub token and no provider key from the platform: the
coding tool runs with whatever is signed in on this machine (Claude Code's login, OpenCode's
config).

Each turn gets a worktree of its own outside the checkout (`~/.dotrix/worktrees/...`), on the
session's branch or the base branch as the remote has it, so your working copy and its changes are
never touched. A worktree separates directories, it isn't a security boundary: with `srt` (the
sandbox runtime) installed the tool runs inside it (writes only to the worktree, network only to the
model's API), otherwise the turn says it isn't isolated. Worktrees are kept after the turn (nothing
is deleted that you might want); `git worktree prune` and removing the folder clean them up.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform as platform_info
import shlex
import shutil
import signal
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

TOOLS = ("claude-code", "opencode")
# What a sandboxed tool may reach: the model providers' APIs, and the package registries tests need.
ALLOWED_DOMAINS = [
    "api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com",
    "registry.npmjs.org", "pypi.org", "files.pythonhosted.org",
]
DENY_READ = ["~/.ssh", "~/.aws", "~/.config/gcloud", "~/.gnupg", "~/.netrc", "~/.docker"]
EVENTS_PER_BEAT = 50
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
    def named(cls, name: str, *, isolated: bool) -> Tool:
        if name == "claude-code":
            # Without a sandbox it may only edit files; inside srt it may run commands too.
            argv = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits"]
            if isolated:
                argv += ["--allowedTools", "Bash"]
            return cls(name, argv)
        if name == "opencode":
            return cls(name, ["opencode", "run", "--format", "json"])
        raise ValueError(f"Unknown coding tool {name!r} (one of {', '.join(TOOLS)})")


def found_tools() -> list[str]:
    """The coding tools on this machine's PATH, preferred first."""
    return [name for name, binary in (("claude-code", "claude"), ("opencode", "opencode")) if shutil.which(binary)]


def has_srt() -> bool:
    return shutil.which("srt") is not None


@dataclass
class Outcome:
    events: list[dict[str, str]] = field(default_factory=list)
    summary: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


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
                args = item.get("input") or {}
                target = args.get("file_path") or args.get("command") or args.get("pattern") or ""
                out.events.append({"kind": "tool", "text": f"{item.get('name')} {target}".strip()[:4000]})
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
    elif kind == "tool_use":
        part = event.get("part") or {}
        args = (part.get("state") or {}).get("input") or {}
        out.events.append({"kind": "tool", "text": f"{part.get('tool')} {args.get('path') or args.get('command') or ''}".strip()})
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
    sandbox: str = "auto"  # "auto" (srt when installed), "srt", or "none"
    worktrees: Path = field(default_factory=lambda: Path.home() / ".dotrix" / "worktrees")
    name: str = field(default_factory=socket.gethostname)
    remote: str = "origin"
    echo: Callable[[str], None] = print
    runner_id: str | None = None
    beat_seconds: float | None = None  # between heartbeats while the tool works (default: a third of the lease)

    @property
    def isolation(self) -> str:
        if self.sandbox == "srt":
            if not has_srt():
                raise RuntimeError("srt isn't installed: npm install -g @anthropic-ai/sandbox-runtime")
            return "srt"
        return "srt" if self.sandbox == "auto" and has_srt() else "none"

    def tools(self) -> list[str]:
        if self.tool:
            return [self.tool]
        found = found_tools()
        return found or ([] if self.command is None else ["claude-code"])

    @property
    def base(self) -> str:
        return f"/workspaces/{self.workspace_id}/coding/runners"

    async def register(self) -> dict[str, Any]:
        tools = self.tools()
        if not tools:
            raise RuntimeError("No coding tool here: install Claude Code (`claude`) or OpenCode (`opencode`)")
        runner = await self.api.post(self.base, {
            "name": self.name[:100], "platform": platform_info.system().lower(), "tools": tools,
            "isolation": self.isolation, "project_ids": [self.project_id],
        })
        self.runner_id = runner["id"]
        return runner

    async def once(self) -> bool:
        """Claim one turn and code it; False when none waits."""
        if self.runner_id is None:
            await self.register()
        claimed = await self.api.post(f"{self.base}/{self.runner_id}/claim")
        if not claimed.get("run"):
            return False
        await self.work(claimed["run"])
        return True

    async def serve(self, *, poll_seconds: float = 5, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
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
        await git(self.repo, "worktree", "add", "-q", "--detach", str(tree), "FETCH_HEAD")
        base_sha = (await git(tree, "rev-parse", "HEAD")).strip()
        isolation = self.isolation
        pending.append({"kind": "step", "text": f"Worktree on {ref} at {base_sha[:7]}"
                        + ("" if isolation == "srt" else " (not isolated: install srt to sandbox the tool)")})
        if await beat({"base_sha": base_sha}):
            await report("stopped", base_sha=base_sha)
            return

        if self.command:
            tool = Tool("command", shlex.split(self.command))
        else:
            here = self.tools()
            tool = Tool.named(run["tool"] if run["tool"] in here else here[0], isolated=isolation == "srt")
        argv = self._sandboxed(tool.argv, tree) if isolation == "srt" else tool.argv
        out = Outcome()
        process = await asyncio.create_subprocess_exec(
            *argv, cwd=tree, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=_env(), start_new_session=os.name != "nt",
        )
        assert process.stdin and process.stdout and process.stderr
        process.stdin.write(run["brief"].encode())
        await process.stdin.drain()
        process.stdin.close()
        errors = asyncio.create_task(process.stderr.read())
        stopped = False

        async def read() -> None:
            assert process.stdout
            async for raw in process.stdout:
                before = len(out.events)
                parse_line(raw.decode(errors="replace"), out)
                pending.extend(out.events[before:])

        reading = asyncio.create_task(read())
        last = time.monotonic()
        try:
            while not reading.done():
                await asyncio.wait({reading}, timeout=min(1.0, beat_every))
                if time.monotonic() - last >= beat_every or len(pending) >= EVENTS_PER_BEAT:
                    last = time.monotonic()
                    if await beat():
                        stopped = True
                        await _terminate(process)
        except LeaseLost:
            await _terminate(process)
            self.echo(f"  The platform gave the turn to another attempt; left {tree} as it is")
            raise
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
                await report("failed", base_sha=base_sha, summary=out.summary,
                             error=(stderr or f"{tool.name} exited with {code}")[-2000:], **usage)
            else:
                await report("no_changes", base_sha=base_sha, summary=out.summary, **usage)
            self.echo("  No changes")
            return
        await report("changes", base_sha=base_sha, patch=patch, summary=out.summary or _tail(stderr), **usage)
        self.echo(f"  Changes reported; the worktree stays at {tree}")

    def _sandboxed(self, argv: list[str], tree: Path) -> list[str]:
        """The tool inside srt: writes only to the worktree (and the tools' own state), reads
        everything but credentials, network only to model APIs and package registries."""
        settings = tree.parent / f"{tree.name}.srt.json"
        home = Path.home()
        settings.write_text(json.dumps({
            "filesystem": {
                "denyRead": DENY_READ,
                "allowWrite": [str(tree), str(home / ".claude"), str(home / ".claude.json"),
                               str(home / ".local" / "share" / "opencode"), "/tmp"],
                "denyWrite": [],
            },
            "network": {"allowedDomains": ALLOWED_DOMAINS, "deniedDomains": []},
        }, indent=2), encoding="utf-8")
        return ["srt", "--settings", str(settings), "--", *argv]


def _lost(exc: Exception) -> bool:
    return getattr(exc, "code", None) == "lease_lost"


def _env() -> dict[str, str]:
    """The tool's environment: this machine's, without the platform's token."""
    return {k: v for k, v in os.environ.items() if k not in ("DOTRIX_TOKEN",)}


def _tail(text: str) -> str | None:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1][:2000] if lines else None


async def _terminate(process: asyncio.subprocess.Process) -> None:
    """Interrupt the tool (and what it started), then kill it if it doesn't end."""
    if process.returncode is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGINT)
        else:
            process.terminate()
        await asyncio.wait_for(process.wait(), STOP_GRACE_SECONDS)
    except (TimeoutError, ProcessLookupError):
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
