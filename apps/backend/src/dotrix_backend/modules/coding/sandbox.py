"""Where a coding agent runs: a sandbox per run, holding a copy of the repo and nothing else.

- OpenShell (`DOTRIX_CODING_SANDBOX=openshell`, the development sandbox): one sandbox per run from the coding image,
  under a policy (the workdir writable, the system read-only, the network closed but for what it lists), with the
  model key attached as a provider: OpenShell keeps the key and the sandbox sees a placeholder that its proxy swaps
  in only for the model provider's endpoints. Driven through the OpenShell CLI against the gateway it has selected.
- Docker Cloud (`docker-cloud`, staging and production): a Docker Sandboxes microVM per run, its network limited to
  the model API by Docker's own policy, the key added by Docker outside the sandbox (docker_cloud.py).
- Local (`local`): a temporary folder on this machine, with no isolation at all. For development only; refused in
  production.

None ever receives a GitHub token: the worker clones and pushes outside the sandbox.

The hosts in a session's network policy (network.py) reach OpenShell and Docker Cloud sandboxes: both keep the model
key out of the sandbox, so a listed host can't receive it. OpenShell lists them in the sandbox's policy
(`sandbox_policy`); Docker Cloud in its network policy.
"""
from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import logging
import os
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.code.checkouts import remove_tree

from .tools import CodingTool

logger = logging.getLogger(__name__)

REPO_DIR = "/sandbox/repo"  # the repo's place in an OpenShell sandbox
CAPTURE_LIMIT = 8_000_000  # bytes of a command's output kept when it isn't streamed
STDERR_TAIL = 4_000
CLI_TIMEOUT = 300  # creating, uploading, deleting
EXEC_TIMED_OUT = 124  # `openshell sandbox exec --timeout` ran out (as coreutils' timeout)


class SandboxError(Exception):
    """The sandbox couldn't be set up or used; the message is safe to store and show."""


@dataclass(frozen=True)
class ExecResult:
    code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False
    truncated: bool = False
    raw: bytes = b""  # stdout exactly as the command wrote it (stdout is decoded with replacements)


LineHandler = Callable[[str], Awaitable[None]]


class SandboxSession(Protocol):
    async def exec(
        self, argv: list[str], *, stdin: bytes | None = None, on_line: LineHandler | None = None,
        timeout: float, cancel: asyncio.Event | None = None,
    ) -> ExecResult: ...
    async def close(self) -> None: ...


class CodingSandbox(Protocol):
    kind: str

    async def open(
        self, run_id: uuid.UUID, source: Path, tool: CodingTool, model_key: str, *, allow: list[str] | tuple = (),
    ) -> SandboxSession:
        """A sandbox holding a copy of `source` (a folder named `repo`), where commands run in the
        repo, and `tool` can reach its model with `model_key`, and the `allow` hosts (owners' and admins'
        the network policy; exact, `*.domain`, either with :port) besides."""
        ...


def openshell_endpoint(entry: str) -> dict:
    """One network policy entry (`host`, `*.domain`, either with `:port`; network_policy.py) as an OpenShell endpoint:
    TLS relayed as it is (`tls: skip`), so the sandbox's own client checks the certificate and nothing is inspected.
    `*.domain` means every host under the domain here, so it becomes OpenShell's `**.domain` (`*.` is one label)."""
    from dotrix_engine.network_policy import parse_entry

    parsed = parse_entry(entry)
    return {"host": f"**.{parsed.host}" if parsed.subdomains else parsed.host, "port": parsed.port, "tls": "skip"}


def sandbox_policy(allow: list[str] | tuple = ()) -> dict:
    """The run's OpenShell policy: the workdir (with the repo) writable, the system read-only, /tmp for scratch, and
    a network closed but for the hosts in the session's network policy (`allow`), for any program in the sandbox.
    The model provider attached to the sandbox adds its endpoints (api.anthropic.com for Claude Code, api.openai.com
    for Codex), for the tool's binaries only; the sandbox holds only a placeholder for the key, so no listed host can
    receive it. Nothing reaches GitHub: the worker pushes."""
    network: dict = {}
    if allow:
        network["project_hosts"] = {
            "endpoints": [openshell_endpoint(entry) for entry in allow],
            "binaries": [{"path": "/**"}],
        }
    return {
        "version": 1,
        "filesystem_policy": {
            "include_workdir": True,
            "read_only": ["/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc", "/opt"],
            "read_write": ["/tmp"],
        },
        "landlock": {"compatibility": "hard_requirement"},
        "process": {"run_as_user": "sandbox", "run_as_group": "sandbox"},
        "network_policies": network,
    }


async def run_process(
    argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, stdin: bytes | None = None,
    on_line: LineHandler | None = None, timeout: float, cancel: asyncio.Event | None = None,
) -> ExecResult:
    """Run a command; stream its stdout a line at a time to `on_line`, or keep it (up to a limit).
    Killed (with its process group) on `timeout` or when `cancel` is set."""
    try:
        return await _run_async(argv, cwd=cwd, env=env, stdin=stdin, on_line=on_line, timeout=timeout, cancel=cancel)
    except NotImplementedError:
        # Windows' selector loop (the API and the worker use it there, for psycopg) can't start
        # subprocesses: the same, with threads reading the pipes.
        return await _run_threaded(argv, cwd=cwd, env=env, stdin=stdin, on_line=on_line, timeout=timeout,
                                   cancel=cancel)


async def _run_async(
    argv: list[str], *, cwd: Path | None, env: dict[str, str] | None, stdin: bytes | None,
    on_line: LineHandler | None, timeout: float, cancel: asyncio.Event | None,
) -> ExecResult:
    try:
        process = await asyncio.create_subprocess_exec(
            *argv, cwd=cwd, env=env, start_new_session=True,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=4_000_000,
        )
    except FileNotFoundError as exc:
        raise SandboxError(f"{argv[0]} isn't installed here") from exc
    assert process.stdout is not None and process.stderr is not None
    kept: list[bytes] = []
    size, truncated = 0, False
    err = bytearray()

    async def feed() -> None:
        if stdin is not None and process.stdin is not None:
            try:
                process.stdin.write(stdin)
                await process.stdin.drain()
            finally:
                process.stdin.close()

    async def read_out() -> None:
        nonlocal size, truncated
        async for raw in process.stdout:  # type: ignore[union-attr]
            if on_line is not None:
                await on_line(raw.decode(errors="replace"))
            elif size + len(raw) <= CAPTURE_LIMIT:
                kept.append(raw)
                size += len(raw)
            else:
                truncated = True

    async def read_err() -> None:
        async for raw in process.stderr:  # type: ignore[union-attr]
            err.extend(raw)
            del err[: max(0, len(err) - STDERR_TAIL)]

    work = asyncio.gather(feed(), read_out(), read_err(), process.wait())
    waiters: set[asyncio.Future] = {asyncio.ensure_future(work)}
    stopper = asyncio.ensure_future(cancel.wait()) if cancel is not None else None
    if stopper is not None:
        waiters.add(stopper)
    done, _ = await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    timed_out = not done
    cancelled = stopper is not None and stopper in done
    if timed_out or cancelled:
        _kill(process)
        work.cancel()
        await asyncio.gather(work, return_exceptions=True)  # (collects the cancellation)
    if stopper is not None:
        stopper.cancel()
    if not (timed_out or cancelled):
        await work  # raises what on_line raised
    return ExecResult(
        code=process.returncode, stdout=b"".join(kept).decode(errors="replace"),
        stderr=err.decode(errors="replace"), timed_out=timed_out, cancelled=cancelled, truncated=truncated,
        raw=b"".join(kept),
    )


async def _run_threaded(
    argv: list[str], *, cwd: Path | None, env: dict[str, str] | None, stdin: bytes | None,
    on_line: LineHandler | None, timeout: float, cancel: asyncio.Event | None,
) -> ExecResult:
    loop = asyncio.get_running_loop()
    try:
        process = subprocess.Popen(
            argv, cwd=cwd, env=env, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise SandboxError(f"{argv[0]} isn't installed here") from exc
    assert process.stdout is not None and process.stderr is not None
    lines: asyncio.Queue[bytes | None] = asyncio.Queue()
    err = bytearray()
    lock = threading.Lock()

    def pump_out() -> None:
        for raw in iter(process.stdout.readline, b""):  # type: ignore[union-attr]
            loop.call_soon_threadsafe(lines.put_nowait, raw)
        loop.call_soon_threadsafe(lines.put_nowait, None)

    def pump_err() -> None:
        for raw in iter(process.stderr.readline, b""):  # type: ignore[union-attr]
            with lock:
                err.extend(raw)
                del err[: max(0, len(err) - STDERR_TAIL)]

    def feed() -> None:
        try:
            process.stdin.write(stdin or b"")  # type: ignore[union-attr]
            process.stdin.close()  # type: ignore[union-attr]
        except OSError:
            pass

    for target in (pump_out, pump_err, *([feed] if stdin is not None else [])):
        threading.Thread(target=target, daemon=True).start()
    kept: list[bytes] = []
    size, truncated = 0, False

    async def consume() -> None:
        nonlocal size, truncated
        while (raw := await lines.get()) is not None:
            if on_line is not None:
                await on_line(raw.decode(errors="replace"))
            elif size + len(raw) <= CAPTURE_LIMIT:
                kept.append(raw)
                size += len(raw)
            else:
                truncated = True
        await asyncio.to_thread(process.wait)

    work = asyncio.ensure_future(consume())
    waiters: set[asyncio.Future] = {work}
    stopper = asyncio.ensure_future(cancel.wait()) if cancel is not None else None
    if stopper is not None:
        waiters.add(stopper)
    done, _ = await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    timed_out = not done
    cancelled = stopper is not None and stopper in done
    if timed_out or cancelled:
        process.kill()
        work.cancel()
        await asyncio.gather(work, return_exceptions=True)
        await asyncio.to_thread(process.wait)
    if stopper is not None:
        stopper.cancel()
    if not (timed_out or cancelled):
        await work  # raises what on_line raised
    with lock:
        stderr = err.decode(errors="replace")
    return ExecResult(code=process.returncode, stdout=b"".join(kept).decode(errors="replace"), stderr=stderr,
                      timed_out=timed_out, cancelled=cancelled, truncated=truncated, raw=b"".join(kept))


def _kill(process: asyncio.subprocess.Process) -> None:
    killpg = getattr(os, "killpg", None)  # not on Windows: there, the process alone
    try:
        if killpg is None:
            raise ProcessLookupError
        killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            process.kill()
        except ProcessLookupError:
            pass


# -- Stopping inside a sandbox ---------------------------------------------------------

TURN_PID = "/tmp/dotrix-turn.pid"  # the command a stoppable exec runs, so Stop can signal it in the sandbox
STOP_GRACE = 5.0  # seconds between SIGINT (finish cleanly) and SIGKILL
# Every process under the turn's, frozen as it's found (so none forks or is reparented away while the
# tree is read), then killed. POSIX sh and procps' pgrep, which the coding image and OpenShell have.
_KILL_TREE = (
    'p=$(cat {pid} 2>/dev/null) || exit 0; kill -STOP "$p" 2>/dev/null; all="$p"; level="$p"; '
    'while [ -n "$level" ]; do next=""; for q in $level; do '
    'for c in $(pgrep -P "$q" 2>/dev/null); do kill -STOP "$c" 2>/dev/null; next="$next $c"; done; done; '
    'all="$all $next"; level="$next"; done; kill -KILL $all 2>/dev/null; exit 0'
)

Exec = Callable[..., Awaitable[ExecResult]]


async def interruptible(
    run: Exec, argv: list[str], *, stdin: bytes | None, on_line: LineHandler | None, timeout: float,
    cancel: asyncio.Event | None,
) -> ExecResult:
    """Run `argv` in a sandbox (with `run`, an exec that goes through the sandbox's CLI) so that Stop
    reaches it there: interrupting the CLI client leaves the command running in the sandbox. On
    `cancel`, SIGINT inside (Claude Code ends its turn cleanly, with its final result), then SIGKILL
    to it and its children after a grace; on the time limit, SIGKILL inside too."""
    if cancel is None:
        return await run(argv, stdin=stdin, on_line=on_line, timeout=timeout, cancel=None)

    async def signal_inside(sig: str) -> None:
        # SIGINT goes to the engine alone, so it ends its turn cleanly. SIGKILL ends the whole tree it
        # started: a test runner or dev server under its shell tool, not just its direct children.
        script = f'p=$(cat {TURN_PID} 2>/dev/null) && kill -INT "$p"' if sig == "INT" else _KILL_TREE.format(pid=TURN_PID)
        try:
            await run(["sh", "-c", script], stdin=None, on_line=None, timeout=30, cancel=None)
        except SandboxError as exc:
            logger.warning("couldn't signal the sandbox (%s): %s", sig, exc)

    inner = asyncio.Event()  # stops the CLI client: only after the command inside has had its chance
    wrapped = ["sh", "-c", f'echo $$ > {TURN_PID}; exec "$@"', "sh", *argv]
    work = asyncio.ensure_future(run(wrapped, stdin=stdin, on_line=on_line, timeout=timeout, cancel=inner))
    stopper = asyncio.ensure_future(cancel.wait())
    done, _ = await asyncio.wait({work, stopper}, return_when=asyncio.FIRST_COMPLETED)
    if work in done:
        stopper.cancel()
        result = work.result()
        if result.timed_out:
            await signal_inside("KILL")
        return result
    await signal_inside("INT")
    try:
        result = await asyncio.wait_for(asyncio.shield(work), STOP_GRACE)
    except TimeoutError:
        await signal_inside("KILL")
        inner.set()
        result = await work
    return dataclasses.replace(result, cancelled=True)


# -- OpenShell -------------------------------------------------------------------------


class OpenShellSession:
    def __init__(self, sandbox: OpenShellSandbox, name: str, provider: str, scratch: Path) -> None:
        self.sandbox, self.name, self.provider, self.scratch = sandbox, name, provider, scratch

    async def exec(
        self, argv: list[str], *, stdin: bytes | None = None, on_line: LineHandler | None = None,
        timeout: float, cancel: asyncio.Event | None = None,
    ) -> ExecResult:
        return await interruptible(self._exec, argv, stdin=stdin, on_line=on_line, timeout=timeout, cancel=cancel)

    async def _exec(
        self, argv: list[str], *, stdin: bytes | None = None, on_line: LineHandler | None = None,
        timeout: float, cancel: asyncio.Event | None = None,
    ) -> ExecResult:
        cli = [
            self.sandbox.bin, "sandbox", "exec", "-n", self.name, "--workdir", REPO_DIR, "--no-tty",
            "--no-login-shell", "--timeout", str(int(timeout)), "--", *argv,
        ]
        result = await run_process(cli, env=self.sandbox.cli_env(), stdin=stdin, on_line=on_line,
                                   timeout=timeout + 30, cancel=cancel)
        if result.code == EXEC_TIMED_OUT:  # OpenShell's own `--timeout` ended it
            return dataclasses.replace(result, timed_out=True)
        return result

    async def close(self) -> None:
        for args in (["sandbox", "delete", self.name], ["provider", "delete", self.provider]):
            try:
                await self.sandbox.cli(*args)
            except SandboxError as exc:
                logger.warning("openshell %s %s: %s", args[0], args[1], exc)
        remove_tree(self.scratch)


class OpenShellSandbox:
    kind = "openshell"

    def __init__(self, settings: Settings) -> None:
        self.bin = settings.openshell_bin
        self.image = settings.coding_image

    async def pin_image(self, reference: str) -> OpenShellSandbox:
        """This sandbox, creating from `reference`: an operator-approved image pinned by digest (environments.py) is
        already immutable, so it's used as it is. The platform image (a tag) is used as configured."""
        import copy

        pinned = copy.copy(self)
        pinned.image = reference
        return pinned

    def cli_env(self, **extra: str) -> dict[str, str]:
        """The CLI finds its gateway in the worker's config; nothing else of ours reaches it."""
        keep = ("PATH", "HOME", "XDG_CONFIG_HOME", "OPENSHELL_GATEWAY", "OPENSHELL_CONFIG_DIR", "LANG", "TZ")
        return {**{k: v for k, v in os.environ.items() if k in keep or k.startswith("OPENSHELL_")}, **extra}

    async def cli(self, *args: str, env: dict[str, str] | None = None) -> str:
        result = await run_process([self.bin, *args], env=env or self.cli_env(), timeout=CLI_TIMEOUT)
        if result.timed_out:
            raise SandboxError(f"openshell {args[0]} {args[1]} took too long")
        if result.code != 0:
            lines = result.stderr.strip().splitlines()
            raise SandboxError(f"openshell {args[0]} {args[1]} failed: {lines[-1][:300] if lines else result.code}")
        return result.stdout

    async def open(
        self, run_id: uuid.UUID, source: Path, tool: CodingTool, model_key: str, *, allow: list[str] | tuple = (),
    ) -> SandboxSession:
        # OpenShell names are at most 19 characters; a UUIDv7's last 16 hex digits are its random part.
        name = provider = f"pm-{run_id.hex[-16:]}"
        scratch = Path(tempfile.mkdtemp(prefix="dotrix-openshell-"))
        session = OpenShellSession(self, name, provider, scratch)
        try:
            # The key goes to the CLI by environment (`--credential NAME` reads it), never argv.
            await self.cli("provider", "create", "--name", provider, "--type", tool.provider_type,
                           "--credential", tool.key_env, env=self.cli_env(**{tool.key_env: model_key}))
            policy = scratch / "policy.yaml"
            policy.write_text(json.dumps(sandbox_policy(allow), indent=2))  # JSON is YAML
            await self.cli("sandbox", "create", "--name", name, "--from", self.image, "--policy", str(policy),
                           "--provider", provider, "--label", f"dotrix-run={run_id}", "--detach",
                           "--", "sleep", "infinity")
            await self.cli("sandbox", "upload", name, str(source), str(Path(REPO_DIR).parent), "--no-git-ignore")
        except BaseException:
            await session.close()
            raise
        return session


# -- Docker Cloud's upload -------------------------------------------------------------


def _tar_of(source: Path) -> bytes:
    """`source` as a tar of one folder, `repo` (extracted by the sandbox's own user, so it owns it)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        tar.add(source, arcname="repo")
    return buffer.getvalue()


# -- Local (development) ---------------------------------------------------------------


class LocalSession:
    def __init__(self, root: Path, env: dict[str, str]) -> None:
        self.root, self.env = root, env

    async def exec(
        self, argv: list[str], *, stdin: bytes | None = None, on_line: LineHandler | None = None,
        timeout: float, cancel: asyncio.Event | None = None,
    ) -> ExecResult:
        return await run_process(argv, cwd=self.root / "repo", env=self.env, stdin=stdin, on_line=on_line,
                                 timeout=timeout, cancel=cancel)

    async def close(self) -> None:
        await asyncio.to_thread(remove_tree, self.root)


class LocalSandbox:
    """No isolation: the agent runs as this machine's user, in a temporary copy of the repo, with
    only PATH, a scratch HOME, and the model key in its environment."""

    kind = "local"

    async def open(
        self, run_id: uuid.UUID, source: Path, tool: CodingTool, model_key: str, *, allow: list[str] | tuple = (),
    ) -> SandboxSession:
        root = Path(tempfile.mkdtemp(prefix=f"dotrix-coding-{run_id.hex[:8]}-"))
        await asyncio.to_thread(shutil.copytree, source, root / "repo", symlinks=True)
        (root / "home").mkdir()
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(root / "home"), "LANG": "C.UTF-8",
               **tool.sandbox_env(model_key)}
        return LocalSession(root, env)


def build_sandbox(settings: Settings) -> CodingSandbox | None:
    if settings.coding_sandbox == "openshell":
        return OpenShellSandbox(settings)
    if settings.coding_sandbox == "docker-cloud":
        from .docker_cloud import DockerCloudSandbox  # (imports this module)

        return DockerCloudSandbox(settings)
    if settings.coding_sandbox == "local":
        return LocalSandbox()
    return None
