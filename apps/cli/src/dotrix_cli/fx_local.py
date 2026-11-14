"""fx's local ACP client: private per-turn settings, file edits and the app's browser only.

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
import re
import shutil
import signal
import sys
import tempfile
from pathlib import Path
from typing import Any

AUTH_FILES = ("auth.json", "chatgpt-auth.json", "grok-auth.json", "api-key")
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


def prepare_profile(root: Path, environ: dict[str, str]) -> None:
    """Copy only fx's own model/auth settings, never its full-access mode or remembered grants."""
    source = profile_source(environ)
    saved = read_settings(source)
    settings = {key: saved[key] for key in PROVIDER_SETTINGS if key in saved}
    settings.update({
        "permission_mode": "ask", "auto_upgrade": False, "context": False, "session_titles": False,
        "permission": {"*": "deny", "read": "ask", "glob": "ask", "grep": "ask", "edit": "ask",
                       "read_tool_result": "allow", "capability_search": "allow", "mcp_browser_*": "ask"},
    })
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


def allowed(call: dict[str, Any], root: Path) -> bool:
    """Permission requests use a tool identity observed from the trusted engine's ACP stream."""
    name = call.get("name", "")
    meta = ((call.get("_meta") or {}).get("fx") or {}).get("toolCall") or {}
    mcp = meta.get("mcp") or {}
    if mcp.get("server") == "browser" and name.startswith("mcp_browser_"):
        return True
    if name not in ("write_file", "edit_file", "read_file", "glob_files", "grep_files"):
        return False
    args = call.get("rawInput") or {}
    path = args.get("path") or args.get("file_path")
    if not isinstance(path, str) or not path.strip():
        return False
    candidate = Path(path).expanduser()
    candidate = candidate if candidate.is_absolute() else root / candidate
    try:
        return candidate.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def emit(kind: str, **values: Any) -> None:
    print(json.dumps({"type": kind, **values}), flush=True)


async def run(profile: Path, browser: Path | None = None) -> int:
    binary = shutil.which("fx")
    if binary is None:
        emit("error", message="The local coding tool is not installed")
        return 1
    brief = sys.stdin.read()
    root = Path.cwd().resolve()
    servers = []
    if browser is not None:
        configured = json.loads(browser.read_text())["mcpServers"]["browser"]
        servers = [{"type": "http", "name": "browser", "url": configured["url"],
                    "headers": [{"name": name, "value": value} for name, value in configured["headers"].items()]}]
    # Only the child gets this private home. Its mode changes and sessions never touch the person's profile.
    child_env = {**os.environ, "HOME": str(profile), "USERPROFILE": str(profile), "FX_HOME": str(profile / ".fx"),
                 "FX_AUTO_UPGRADE": "0", "FX_SOUND": "0", "FX_NO_OPEN_BROWSER": "1", "NO_COLOR": "1"}
    version = await asyncio.create_subprocess_exec(binary, "--version", env=child_env,
                                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        version_text, _ = await asyncio.wait_for(version.communicate(), timeout=15)
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", version_text.decode())
        if version.returncode != 0 or match is None or tuple(map(int, match.groups())) < (0, 0, 16):
            raise ValueError("Unsupported local policy")
    except (TimeoutError, ValueError):
        if version.returncode is None:
            version.kill()
            await version.wait()
        emit("error", message="Update the local coding tool before using it with this runner")
        return 1
    probe = await asyncio.create_subprocess_exec(binary, "permissions", "--json", env=child_env,
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, _ = await asyncio.wait_for(probe.communicate(), timeout=15)
        policy = json.loads(stdout)
        expected = json.loads((profile / ".fx/settings.json").read_text())["permission"]
        loaded = {rule["permission"]: rule["action"] for rule in policy.get("rules", []) if rule.get("pattern") == "*"}
        if probe.returncode != 0 or policy.get("mode") != "ask" or any(loaded.get(key) != value for key, value in expected.items()):
            raise ValueError("The local permission policy was not loaded")
    except (TimeoutError, ValueError, KeyError, TypeError):
        if probe.returncode is None:
            probe.kill()
            await probe.wait()
        emit("error", message="The local permission policy was not loaded; update the coding tool and try again")
        return 1
    child = await asyncio.create_subprocess_exec(binary, "acp", env=child_env, stdin=asyncio.subprocess.PIPE,
                                                 stdout=asyncio.subprocess.PIPE, stderr=None, limit=16 * 1024 * 1024)
    assert child.stdin and child.stdout
    pending: dict[int, asyncio.Future] = {}
    calls: dict[str, dict] = {}
    counter = 0
    session_id = None
    cancelled = False
    text: list[str] = []
    last = ""

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

    async def request(method, params):
        nonlocal counter
        counter += 1
        future = asyncio.get_running_loop().create_future()
        identity = counter
        pending[identity] = future
        send({"id": identity, "method": method, "params": params})
        try:
            return await future if method == "session/prompt" else await asyncio.wait_for(future, timeout=30)
        finally:
            pending.pop(identity, None)

    async def read():
        assert child.stdout
        try:
            while line := await child.stdout.readline():
                value = json.loads(line)
                if "method" not in value and value.get("id") in pending:
                    future = pending.pop(value["id"])
                    if value.get("error"):
                        future.set_exception(RuntimeError(str(value["error"].get("message", "The local turn failed"))))
                    else:
                        future.set_result(value.get("result"))
                elif value.get("method") == "session/update":
                    update = value.get("params", {}).get("update") or {}
                    kind = update.get("sessionUpdate")
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
                               if allowed(call, root) and option else {"outcome": "cancelled"})
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
        session = await request("session/new", {"cwd": str(root), "mcpServers": servers})
        session_id = session["sessionId"]
        await request("session/set_mode", {"sessionId": session_id, "modeId": "ask"})
        result = await request("session/prompt", {"sessionId": session_id, "prompt": [{"type": "text", "text": brief}]})
        flush()
        emit("done", final=last, usage=result.get("usage"), stopReason="cancelled" if cancelled else result.get("stopReason"))
        return 0 if cancelled or result.get("stopReason") == "end_turn" else 1
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--browser-config", type=Path)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.profile, args.browser_config)))


if __name__ == "__main__":
    main()
