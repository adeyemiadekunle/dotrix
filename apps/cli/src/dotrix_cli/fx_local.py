"""fx 0.0.18 local ACP client: shell/file tools inside a Linux namespace, and the app browser.

The cloud driver deliberately grants full access inside its sandbox. This client never
does: unknown permissions are refused, edits must stay in the worktree, and the ACP
server list is authoritative. The parent's runner owns and removes the temporary profile.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import posixpath
import shutil
import signal
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from . import bundled

# The kernel boundary, not fx's wildcard permission rules, protects native work.
# fx_native.available() refuses unsupported hosts; there is no unconfined fallback.
NATIVE_FX_POLICY_VALIDATED = True
NATIVE_FX_REFUSAL = ("Local execution requires OS sandbox isolation (Linux Bubblewrap, macOS Seatbelt, or WSL 2 on Windows) "
                     "and the tested coding runtime. Use cloud coding or another local runtime on this computer.")
if sys.platform == "linux":
    # Ubuntu 24.04 and later allow user namespaces only to the bwrap their own package installs.
    NATIVE_FX_REFUSAL += (" On Linux, install your distribution's bubblewrap package (on Ubuntu: sudo apt install "
                          "bubblewrap), which some distributions require in place of the bundled one.")


def refusal() -> str:
    """Why native fx can't run here, saying how to install what is missing where Dotrix knows (WSL on Windows)."""
    from .fx_native import fx_refusal

    return fx_refusal() or NATIVE_FX_REFUSAL

AUTH_FILES = ("auth.json", "chatgpt-auth.json", "grok-auth.json", "api-key")
# Kai's contract ends every brief under this heading (the backend's coding/brief.py, CONTRACT_HEADING). fx takes it
# as the session's system profile, as a cloud turn does, rather than as words in the conversation.
CONTRACT_HEADING = "# How Kai works"
PROVIDER_SETTINGS = ("provider", "providers", "models", "credential_source", "effort")


def profile_source(environ: dict[str, str]) -> Path:
    return Path(environ.get("FX_HOME") or Path(environ.get("HOME") or environ.get("USERPROFILE") or Path.home()) / ".fx")


def read_settings(source: Path) -> dict[str, Any]:
    path = source / "settings.json"
    if not path.is_file():
        return {}
    if os.name != "nt":
        for candidate in (source, path):
            metadata = candidate.stat()
            if metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
                raise ValueError("Make your local model profile private before using it")
    if path.stat().st_size > 65_536:
        raise ValueError("The local model settings are too large")
    settings = json.loads(path.read_text())
    if not isinstance(settings, dict):
        raise ValueError("The local model settings must be an object")
    return settings


def prepare_profile(root: Path, environ: dict[str, str], *, expected_model: str | None = None) -> None:
    """Copy only fx's own model/auth settings, never its full-access mode or remembered grants."""
    source = profile_source(environ)
    saved = read_settings(source)
    if expected_model:
        model_name = expected_model.partition(":")[2] or expected_model
        if saved.get("models", {}).get(saved.get("provider")) != model_name:
            raise ValueError("The local connection's model does not match this session; choose a matching model or start a new session")
    settings = {key: saved[key] for key in PROVIDER_SETTINGS if key in saved}
    settings.update({
        # The repository is data, never configuration (fx's project_config; FX_PROJECT_CONFIG in fx_native too).
        "permission_mode": "ask", "auto_upgrade": False, "context": False, "project_config": False, "max_subagents": 2, "session_titles": False,
        "permission": {"*": "deny", "web_search": "deny", "bash": "ask", "toolbox": "allow", "subagent": "deny", "read": "ask", "glob": "ask", "grep": "ask", "edit": "ask",
                       "read_tool_result": "allow", "capability_search": "allow", "mcp_browser_*": "ask"},
    })
    if environ.get("DOTRIX_CODING_WEB_TOOLS", "").lower() in ("1", "true"):
        settings["permission"]["mcp_research_*"] = "ask"
    folder = root / ".fx"
    folder.mkdir(mode=0o700, parents=True)
    target = folder / "settings.json"
    with target.open("x", encoding="utf-8") as stream:
        target.chmod(0o600)
        json.dump(settings, stream)
    originals = {}
    for name in AUTH_FILES:
        original = source / name
        if original.is_file():
            if original.stat().st_size > 1_048_576:
                raise ValueError("The local sign-in file is too large")
            destination = folder / name
            with destination.open("xb") as stream:
                destination.chmod(0o600)
                content = original.read_bytes()
                stream.write(content)
                originals[name] = hashlib.sha256(content).hexdigest()
    manifest = root / "auth-source.json"
    with manifest.open("x", encoding="utf-8") as stream:
        manifest.chmod(0o600)
        json.dump({"source": str(source.resolve()), "originals": originals}, stream)


def save_refreshed_auth(root: Path) -> None:
    """Keep refreshed logins, without replacing a sign-in changed outside this turn."""
    manifest = root / "auth-source.json"
    if not manifest.is_file():
        return  # Preparation may have failed before any credentials were copied.
    saved = json.loads(manifest.read_text())
    for name in AUTH_FILES:
        digest = saved["originals"].get(name)
        current = root / ".fx" / name
        original = Path(saved["source"]) / name
        if digest is None or not current.is_file() or not original.is_file():
            continue
        if current.stat().st_size > 1_048_576:
            raise ValueError("The refreshed local sign-in file is too large")
        content = current.read_bytes()
        if hashlib.sha256(content).hexdigest() == digest:
            continue
        if hashlib.sha256(original.read_bytes()).hexdigest() != digest:
            continue  # Another local sign-in wins over this turn's older credentials.
        descriptor, temporary = tempfile.mkstemp(prefix=".dotrix-auth-", dir=original.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
            os.replace(temporary, original)
        finally:
            Path(temporary).unlink(missing_ok=True)


def allowed(call: dict[str, Any], root: Path | PurePosixPath, *, research: bool = False) -> bool:
    """Permission requests use a tool identity observed from the trusted engine's ACP stream."""
    name = call.get("name", "")
    meta = ((call.get("_meta") or {}).get("fx") or {}).get("toolCall") or {}
    mcp = meta.get("mcp") or {}
    if mcp.get("server") == "browser" and name.startswith("mcp_browser_"):
        return True
    if name == "shell":
        return True  # The entire runtime and its descendants are inside the OS namespace.
    if research and mcp.get("server") == "research" and name in ("mcp_research_web_search", "mcp_research_fetch_page"):
        return True
    if name not in ("write_file", "edit_file", "read_file", "glob_files", "grep_files"):
        return False
    args = call.get("rawInput") or {}
    path = args.get("path") or args.get("file_path")
    if not isinstance(path, str) or not path.strip():
        return False
    if not isinstance(root, Path):
        # The engine's own paths, in WSL: this host can't resolve them, and the sandbox binds only the worktree
        # and the profile, so a lexical check suffices.
        posix = PurePosixPath(path)
        posix = PurePosixPath(posixpath.normpath(str(posix if posix.is_absolute() else root / posix)))
        return posix == root or root in posix.parents
    candidate = Path(path).expanduser()
    candidate = candidate if candidate.is_absolute() else root / candidate
    try:
        return candidate.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def split_contract(brief: str) -> tuple[str, str | None]:
    """The turn's task and Kai's contract, split at the contract's heading (its last one: the platform appends the
    contract after everything else, so a heading quoted in an issue stays in the task). None: no contract (an older
    platform), and the brief goes whole."""
    task, found, contract = brief.rpartition("\n" + CONTRACT_HEADING + "\n")
    if not found:
        return brief, None
    return task.rstrip() + "\n", (CONTRACT_HEADING + "\n" + contract).strip()


_MAX_SESSION_BYTES = 16 * 1024 * 1024
_MAX_SESSION_FILES = 2_000


def digest_of(contract: str | None) -> str | None:
    if not contract or not contract.strip():
        return None
    return hashlib.sha256(contract.encode("utf-8")).hexdigest()


def _check_private_dir(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("The saved local coding session state is invalid")
    if os.name != "nt":
        metadata = path.lstat()
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise ValueError("Make your local coding session state private before using it")


def _read_regular_bytes(src: Path, budget: list[int]) -> bytes:
    if src.is_symlink():
        raise ValueError("The local coding session state must not contain symbolic links")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(src, flags)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("The local coding session state contains an unsupported entry")
        if budget[1] <= 0 or metadata.st_size > budget[0]:
            raise ValueError("The local coding session state is too large")
        budget[0] -= metadata.st_size
        budget[1] -= 1
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            data = stream.read(metadata.st_size + 1)
        if len(data) > metadata.st_size:
            raise ValueError("The local coding session state changed while reading")
        return data
    finally:
        if fd >= 0:
            os.close(fd)


def _copy_file_safe(src: Path, dst: Path, budget: list[int]) -> None:
    data = _read_regular_bytes(src, budget)
    descriptor = os.open(dst, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
    dst.chmod(0o600)


def _copy_tree_safe(src: Path, dst: Path, budget: list[int]) -> None:
    if src.is_symlink() or not src.is_dir():
        raise ValueError("The local coding session state must not contain symbolic links")
    dst.mkdir(mode=0o700, parents=True, exist_ok=True)
    dst.chmod(0o700)
    with os.scandir(src) as entries:
        for entry in entries:
            child_src = Path(entry.path)
            child_dst = dst / entry.name
            if entry.is_symlink():
                raise ValueError("The local coding session state must not contain symbolic links")
            if entry.is_dir(follow_symlinks=False):
                _copy_tree_safe(child_src, child_dst, budget)
            elif entry.is_file(follow_symlinks=False):
                _copy_file_safe(child_src, child_dst, budget)
            else:
                raise ValueError("The local coding session state contains an unsupported entry")


def restore_session_state(profile: Path, state_dir: Path) -> None:
    """Restore the session record and saved conversation from `state_dir` into `profile/.fx`."""
    if not state_dir.exists():
        return
    _check_private_dir(state_dir)
    fx_dir = profile / ".fx"
    fx_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    budget = [_MAX_SESSION_BYTES, _MAX_SESSION_FILES]
    record = state_dir / "dotrix-session.json"
    if record.exists():
        _copy_file_safe(record, fx_dir / "dotrix-session.json", budget)
    sessions = state_dir / "sessions"
    if sessions.exists():
        _copy_tree_safe(sessions, fx_dir / "sessions", budget)


def save_session_state(profile: Path, state_dir: Path) -> None:
    """Persist the session record and conversation from `profile/.fx` to `state_dir`."""
    fx_dir = profile / ".fx"
    record = fx_dir / "dotrix-session.json"
    sessions = fx_dir / "sessions"
    if not record.exists() and not sessions.exists():
        return
    state_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{state_dir.name}-", dir=state_dir.parent))
    previous: Path | None = None
    try:
        staging.chmod(0o700)
        budget = [_MAX_SESSION_BYTES, _MAX_SESSION_FILES]
        if record.exists():
            _copy_file_safe(record, staging / "dotrix-session.json", budget)
        if sessions.exists():
            _copy_tree_safe(sessions, staging / "sessions", budget)
        if state_dir.is_symlink():
            raise ValueError("The local coding session state directory must not be a link")
        if state_dir.exists():
            previous = Path(tempfile.mkdtemp(prefix=f".{state_dir.name}-old-", dir=state_dir.parent))
            previous.rmdir()
            os.replace(state_dir, previous)
        os.replace(staging, state_dir)
        staging = None  # type: ignore[assignment]
        if previous is not None:
            shutil.rmtree(previous, ignore_errors=True)
            previous = None
    except BaseException:
        if previous is not None and not state_dir.exists():
            with_restore = os.replace
            try:
                with_restore(previous, state_dir)
            except OSError:
                pass
        raise
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if previous is not None and previous.exists():
            shutil.rmtree(previous, ignore_errors=True)


class _RpcError(RuntimeError):
    def __init__(self, code: Any, message: str) -> None:
        super().__init__(message)
        self.code = code


def emit(kind: str, **values: Any) -> None:
    print(json.dumps({"type": kind, **values}), flush=True)


async def run(profile: Path, browser: Path | None = None, steer_dir: Path | None = None,
              *, resume: bool = False, pinned_digest: str | None = None) -> int:
    from .fx_native import fx_available, launch

    if not NATIVE_FX_POLICY_VALIDATED or not fx_available():
        emit("error", message=refusal())
        return 1
    # On Windows, the WSL distribution's own fx runs (fx_wsl, checked by fx_available), so none is needed here.
    binary = bundled.fx() or ("fx" if sys.platform == "win32" else None)
    if binary is None:
        emit("error", message="The local coding tool is not installed")
        return 1
    brief, contract = split_contract(sys.stdin.read())
    record_path = profile / ".fx" / "dotrix-session.json"
    kept: dict[str, Any] = {}
    if resume and record_path.exists():
        if record_path.is_symlink() or not record_path.is_file():
            emit("error", message="This coding session's saved state doesn't match the profile it was started with; start a new session")
            return 1
        try:
            loaded = json.loads(record_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                kept = loaded
        except (OSError, ValueError):
            emit("error", message="This coding session's saved state couldn't be read; start a new session")
            return 1
    previous_session = kept.get("fxSession") if isinstance(kept.get("fxSession"), str) and kept.get("fxSession") else None
    if previous_session is not None:
        expected = kept.get("profileDigest")
        recomputed = digest_of(kept.get("profile")) if isinstance(kept.get("profile"), str) else None
        legacy = "profile" not in kept and expected is None
        contract_digest = digest_of(contract)
        if (
            (not legacy and "profile" not in kept)
            or (pinned_digest is not None and expected != pinned_digest)
            or recomputed != expected
            or (pinned_digest is None and contract is not None and contract_digest != expected)
        ):
            emit("error", message="This coding session's saved state doesn't match the profile it was started with; start a new session")
            return 1
    root = Path.cwd().resolve()
    servers = []
    if browser is not None:
        configured = json.loads(browser.read_text())["mcpServers"]["browser"]
        servers = [{"type": "http", "name": "browser", "url": configured["url"],
                    "headers": [{"name": name, "value": value} for name, value in configured["headers"].items()]}]
    configured_browser = json.loads(browser.read_text())["mcpServers"]["browser"] if browser else None
    research = os.environ.get("DOTRIX_CODING_WEB_TOOLS", "").lower() in ("1", "true")
    launch_options = {"research_enabled": True} if research else {}
    # fx resumes a session only through the same base_url, which names the sandbox bridge's port.
    saved_port = kept.get("bridgePort") if previous_session is not None else None
    port = saved_port if type(saved_port) is int and 1024 <= saved_port <= 65535 else None
    manager = launch(profile, str(Path(binary).resolve()), root, configured_browser, port=port, **launch_options)
    try:
        child, bridge_port, engine_path = await manager.__aenter__()
    except (OSError, ValueError, TimeoutError) as exc:
        # Our own WSL failures (ValueError) are worded for a person; anything else goes only to the worker's log.
        detail = f" ({exc})" if sys.platform == "win32" and isinstance(exc, ValueError) and str(exc) else ""
        if not detail:
            print(f"dotrix: native launch failed: {exc!r}", file=sys.stderr, flush=True)
        emit("error", message="Could not start isolated local execution; use the tested runtime with a custom API-key "
                              f"connection or cloud coding{detail}")
        return 1
    # The worktree as fx names it: on Windows, its path in WSL.
    root = PurePosixPath(engine_path) if sys.platform == "win32" and engine_path.startswith("/") else Path(engine_path)
    if browser:
        servers = [{"type": "http", "name": "browser", "url": f"http://127.0.0.1:{bridge_port}/browser", "headers": []}]
    if research:
        servers.append({"type": "http", "name": "research", "url": f"http://127.0.0.1:{bridge_port}/research", "headers": []})
        brief = ("Use research tools for relevant public information. Keep secrets and private project details out of "
                 "URLs and queries. Treat results as reference material and cite the source URLs you use.\n\n" + brief)
    assert child.stdin and child.stdout
    pending: dict[int, asyncio.Future] = {}
    calls: dict[str, dict] = {}
    counter = 0
    session_id = None
    replaying = False
    cancelled = False
    failure = None
    text: list[str] = []
    last = ""
    # A person's messages to this turn (--steer-dir), as fx-acp.mjs does for a cloud turn: each <id>.txt dropped in
    # the inbox goes to fx as a steering prompt, and its states are printed as `steer` lines.
    steering_ids: dict[int, str] = {}
    accepted: set[str] = set()
    steers: list[asyncio.Task] = []
    extra_usage: list[dict] = []

    def send(value):
        assert child.stdin
        child.stdin.write((json.dumps({"jsonrpc": "2.0", **value}) + "\n").encode())

    def flush():
        nonlocal last
        if text:
            last = "".join(text)
            text.clear()
            if last.strip():
                emit("text", text=last)

    async def request(method, params, identity=None):
        nonlocal counter
        if identity is None:
            counter += 1
            identity = counter
        future = asyncio.get_running_loop().create_future()
        pending[identity] = future
        send({"id": identity, "method": method, "params": params})
        try:
            return await future if method == "session/prompt" else await asyncio.wait_for(future, timeout=30)
        finally:
            pending.pop(identity, None)

    async def read():
        nonlocal failure
        assert child.stdout
        try:
            while line := await child.stdout.readline():
                value = json.loads(line)
                if "method" not in value and value.get("id") in pending:
                    future = pending.pop(value["id"])
                    if value.get("error"):
                        err = value["error"]
                        future.set_exception(_RpcError(err.get("code"), str(err.get("message", "The local turn failed"))))
                    else:
                        future.set_result(value.get("result"))
                elif value.get("method") == "session/update":
                    if replaying:
                        continue
                    update = value.get("params", {}).get("update") or {}
                    kind = update.get("sessionUpdate")
                    recovery = ((update.get("_meta") or {}).get("fx") or {}).get("modelResponseRecovery")
                    if isinstance(recovery, dict) and recovery.get("state") in ("need_user", "failed") and not cancelled and not failure:
                        failure = "The model request needs attention; check your provider connection and try again"
                        emit("error", message=failure)
                        if session_id:
                            send({"method": "session/cancel", "params": {"sessionId": session_id}})
                    steer_id = steering_ids.get((((update.get("_meta") or {}).get("fx") or {}).get("steering") or {}).get("requestId"))
                    if kind == "user_message_chunk" and steer_id and steer_id not in accepted:
                        accepted.add(steer_id)  # fx gave the person's message to the model
                        emit("steer", id=steer_id, state="accepted")
                    if kind == "agent_message_chunk" and update.get("content", {}).get("type") == "text":
                        text.append(update["content"]["text"])
                    elif kind in ("tool_call", "tool_call_update"):
                        identity = str(update.get("toolCallId", ""))
                        if kind == "tool_call" and identity not in calls:
                            calls[identity] = update
                            flush()
                            emit("tool", id=identity, name=update.get("name"), input=update.get("rawInput") or {})
                        if update.get("status") in ("completed", "failed"):
                            output = "".join(item.get("content", {}).get("text", "") for item in update.get("content", [])
                                             if item.get("type") == "content")
                            emit("tool_result", id=identity, status=update["status"], output=output[-64_000:])
                elif value.get("method") == "session/request_permission":
                    params = value.get("params") or {}
                    call = calls.get(str((params.get("toolCall") or {}).get("toolCallId", "")), {})
                    option = next((item for item in params.get("options", []) if item.get("kind") == "allow_once"), None)
                    outcome = ({"outcome": "selected", "optionId": option["optionId"]}
                               if allowed(call, root, research=research) and option else {"outcome": "cancelled"})
                    send({"id": value["id"], "result": {"outcome": outcome}})
                elif "id" in value and "method" in value:
                    send({"id": value["id"], "error": {"code": -32601, "message": "Not supported"}})
        except Exception as exc:
            for future in pending.values():
                if not future.done():
                    future.set_exception(exc)
        finally:
            for future in pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("The local coding process stopped"))

    reader = asyncio.create_task(read())

    def cancel(*args):
        nonlocal cancelled
        cancelled = True
        if session_id and child.returncode is None and not child.stdin.is_closing():
            send({"method": "session/cancel", "params": {"sessionId": session_id}})

    previous = {}
    for name in (signal.SIGINT, signal.SIGTERM):
        previous[name] = signal.signal(name, cancel)
    try:
        await request("initialize", {"protocolVersion": 1, "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False},
                                                                                  "terminal": False},
                                     "clientInfo": {"name": "dotrix", "version": "1"}})
        # Kai's contract as the session's system profile (ACP's systemPrompt), as on a cloud turn. When resuming
        # a managed local session, keep the original session and verify the profile digest before starting.
        session_resumed = False
        fresh = False
        profile_digest = kept.get("profileDigest") if previous_session else None
        if previous_session is not None:
            replaying = True
            try:
                try:
                    await request("session/resume", {"sessionId": previous_session, "cwd": str(root), "mcpServers": servers})
                except _RpcError as exc:
                    if exc.code != -32601:
                        raise
                    await request("session/load", {"sessionId": previous_session, "cwd": str(root), "mcpServers": servers})
                session_id = previous_session
                session_resumed = True
            except _RpcError:
                fresh = True
            finally:
                replaying = False
        if not session_resumed:
            opened = {"cwd": str(root), "mcpServers": servers}
            if contract:
                opened["systemPrompt"] = [{"type": "text", "text": contract}]
            session = await request("session/new", opened)
            session_id = session["sessionId"]
            profile_digest = digest_of(contract)
            # The bridge's port is part of the session's connection, so the next turn asks for it again.
            record = {"fxSession": session_id, "profileDigest": profile_digest, "bridgePort": bridge_port,
                      **({"profile": contract} if contract and contract.strip() else {})}
            descriptor = os.open(record_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(record, stream)
            record_path.chmod(0o600)
        await request("session/set_mode", {"sessionId": session_id, "modeId": "ask"})
        emit("started", resumed=session_resumed,
             **({"profileDigest": profile_digest} if profile_digest else {}),
             **({"fresh": True} if fresh else {}))
        inbox_open = False
        if steer_dir is not None:
            try:
                shutil.rmtree(steer_dir, ignore_errors=True)
                steer_dir.mkdir(mode=0o700, parents=True)
                inbox_open = True
                emit("steering", open=True)
            except OSError:
                pass  # without an inbox the turn goes on; messages sent to it go to the next turn

        async def one_steer(key: str, message: str) -> None:
            nonlocal counter
            counter += 1
            identity = counter
            steering_ids[identity] = key
            emit("steer", id=key, state="sent")
            try:
                answer = await request("session/prompt", {"sessionId": session_id, "prompt": [{"type": "text", "text": message}],
                                                          "_meta": {"fx": {"steer": True}}}, identity)
            except Exception as exc:
                emit("steer", id=key, state="cancelled" if cancelled else "rejected", message=str(exc)[:200])
                return
            how = ((answer or {}).get("_meta") or {}).get("fx", {}).get("steering")
            if not how and (answer or {}).get("usage"):
                extra_usage.append(answer["usage"])  # it came as the turn closed input: fx ran it as a turn of its own
            emit("steer", id=key, state="cancelled" if how == "dropped" or (answer or {}).get("stopReason") == "cancelled" else "delivered")

        async def watch_inbox() -> None:
            while True:
                await asyncio.sleep(0.25)
                if cancelled:
                    continue
                for item in sorted(steer_dir.glob("*.txt")) if steer_dir else []:
                    key = item.name[:-4]
                    try:
                        message = item.read_text(encoding="utf-8")
                        item.unlink()
                    except OSError:
                        continue
                    if not message.strip():
                        emit("steer", id=key, state="rejected", message="The message was empty")
                        continue
                    flush()
                    steers.append(asyncio.create_task(one_steer(key, message)))

        watcher = asyncio.create_task(watch_inbox()) if inbox_open else None
        try:
            result = await request("session/prompt", {"sessionId": session_id, "prompt": [{"type": "text", "text": brief}]})
        finally:
            if watcher is not None:
                watcher.cancel()
                shutil.rmtree(steer_dir, ignore_errors=True)  # closed: what's left was never sent, and goes to the next turn
                await asyncio.gather(*steers, return_exceptions=True)
        flush()
        usage = result.get("usage")
        for more in extra_usage:
            usage = {**(usage or {}), **{k: (usage or {}).get(k, 0) + v for k, v in more.items() if isinstance(v, (int, float))}}
        emit("done", final=last, usage=usage, stopReason="refused" if failure else "cancelled" if cancelled else result.get("stopReason"))
        return 0 if not failure and (cancelled or result.get("stopReason") == "end_turn") else 1
    except Exception as exc:
        emit("error", message=str(exc)[:2000])
        return 1
    finally:
        for name, handler in previous.items():
            signal.signal(name, handler)
        child.stdin.close()
        try:
            await asyncio.wait_for(child.wait(), timeout=3)
        except TimeoutError:
            child.kill()
            await child.wait()
        await reader
        await manager.__aexit__(None, None, None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--browser-config", type=Path)
    parser.add_argument("--steer-dir", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--profile-digest")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.profile, args.browser_config, args.steer_dir,
                                    resume=args.resume, pinned_digest=args.profile_digest)))


if __name__ == "__main__":
    main()
