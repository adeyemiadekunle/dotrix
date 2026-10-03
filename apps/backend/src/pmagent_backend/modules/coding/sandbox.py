"""Where a coding agent runs: a sandbox per run, holding a copy of the repo and nothing else.

- OpenShell (`PMAGENT_CODING_SANDBOX=openshell`): one sandbox per run from the coding image,
  under a policy (the workdir writable, the system read-only, no network rule of its own), with
  the model key attached as a provider: OpenShell keeps the key and the sandbox sees a
  placeholder that its proxy swaps in only for the model provider's endpoints. Driven through
  the OpenShell CLI against the gateway it has selected.
- Local (`local`): a temporary folder on this machine, with no isolation at all. For
  development only; refused in production.

Neither ever receives a GitHub token: the worker clones and pushes outside the sandbox.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import shutil
import signal
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pmagent_backend.core.settings import Settings

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


LineHandler = Callable[[str], Awaitable[None]]


class SandboxSession(Protocol):
    async def exec(
        self, argv: list[str], *, stdin: bytes | None = None, on_line: LineHandler | None = None,
        timeout: float, cancel: asyncio.Event | None = None,
    ) -> ExecResult: ...
    async def close(self) -> None: ...


class CodingSandbox(Protocol):
    kind: str

    async def open(self, run_id: uuid.UUID, source: Path, tool: CodingTool, model_key: str) -> SandboxSession:
        """A sandbox holding a copy of `source` (a folder named `repo`), where commands run in the
        repo, and `tool` can reach its model with `model_key`."""
        ...


def sandbox_policy() -> dict:
    """The run's OpenShell policy: the workdir (with the repo) writable, the system read-only,
    /tmp for scratch; no network of its own. The model provider attached to the sandbox adds
    its endpoints (api.anthropic.com for Claude Code, api.openai.com for Codex), for the tool's
    binaries only. Nothing reaches GitHub: the worker pushes."""
    return {
        "version": 1,
        "filesystem_policy": {
            "include_workdir": True,
            "read_only": ["/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc", "/opt"],
            "read_write": ["/tmp"],
        },
        "landlock": {"compatibility": "hard_requirement"},
        "process": {"run_as_user": "sandbox", "run_as_group": "sandbox"},
        "network_policies": {},
    }


async def run_process(
    argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, stdin: bytes | None = None,
    on_line: LineHandler | None = None, timeout: float, cancel: asyncio.Event | None = None,
) -> ExecResult:
    """Run a command; stream its stdout a line at a time to `on_line`, or keep it (up to a limit).
    Killed (with its process group) on `timeout` or when `cancel` is set."""
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
    )


def _kill(process: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            process.kill()
        except ProcessLookupError:
            pass


# -- OpenShell -------------------------------------------------------------------------


class OpenShellSession:
    def __init__(self, sandbox: OpenShellSandbox, name: str, provider: str, scratch: Path) -> None:
        self.sandbox, self.name, self.provider, self.scratch = sandbox, name, provider, scratch

    async def exec(
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
        shutil.rmtree(self.scratch, True)


class OpenShellSandbox:
    kind = "openshell"

    def __init__(self, settings: Settings) -> None:
        self.bin = settings.openshell_bin
        self.image = settings.coding_image

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

    async def open(self, run_id: uuid.UUID, source: Path, tool: CodingTool, model_key: str) -> SandboxSession:
        # OpenShell names are at most 19 characters; a UUIDv7's last 16 hex digits are its random part.
        name = provider = f"pm-{run_id.hex[-16:]}"
        scratch = Path(tempfile.mkdtemp(prefix="pmagent-openshell-"))
        session = OpenShellSession(self, name, provider, scratch)
        try:
            # The key goes to the CLI by environment (`--credential NAME` reads it), never argv.
            await self.cli("provider", "create", "--name", provider, "--type", tool.provider_type,
                           "--credential", tool.key_env, env=self.cli_env(**{tool.key_env: model_key}))
            policy = scratch / "policy.yaml"
            policy.write_text(json.dumps(sandbox_policy(), indent=2))  # JSON is YAML
            await self.cli("sandbox", "create", "--name", name, "--from", self.image, "--policy", str(policy),
                           "--provider", provider, "--label", f"pmagent-run={run_id}", "--detach",
                           "--", "sleep", "infinity")
            await self.cli("sandbox", "upload", name, str(source), str(Path(REPO_DIR).parent), "--no-git-ignore")
        except BaseException:
            await session.close()
            raise
        return session


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
        await asyncio.to_thread(shutil.rmtree, self.root, True)


class LocalSandbox:
    """No isolation: the agent runs as this machine's user, in a temporary copy of the repo, with
    only PATH, a scratch HOME, and the model key in its environment."""

    kind = "local"

    async def open(self, run_id: uuid.UUID, source: Path, tool: CodingTool, model_key: str) -> SandboxSession:
        root = Path(tempfile.mkdtemp(prefix=f"pmagent-coding-{run_id.hex[:8]}-"))
        await asyncio.to_thread(shutil.copytree, source, root / "repo", symlinks=True)
        (root / "home").mkdir()
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(root / "home"), "LANG": "C.UTF-8",
               tool.key_env: model_key}
        if tool.key_env == "OPENAI_API_KEY":
            env["CODEX_API_KEY"] = model_key  # what `codex exec` reads
        for name in ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL"):  # a proxy in front of the provider
            if os.environ.get(name):
                env[name] = os.environ[name]
        return LocalSession(root, env)


def build_sandbox(settings: Settings) -> CodingSandbox | None:
    if settings.coding_sandbox == "openshell":
        return OpenShellSandbox(settings)
    if settings.coding_sandbox == "local":
        return LocalSandbox()
    return None
