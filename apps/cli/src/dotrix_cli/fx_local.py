"""fx 0.0.17 local ACP client: shell/file tools inside a Linux namespace, and the app browser.

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
import shutil
import signal
import sys
import tempfile
from pathlib import Path
from typing import Any

# The kernel boundary, not fx's wildcard permission rules, protects native work.
# fx_native.available() refuses unsupported hosts; there is no unconfined fallback.
NATIVE_FX_POLICY_VALIDATED = True
NATIVE_FX_REFUSAL = ("Local execution requires Linux Bubblewrap with working user/network namespaces and the tested coding runtime. "
                     "Use cloud coding or another local runtime on this computer.")

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
        "permission": {"*": "deny", "bash": "ask", "toolbox": "allow", "subagent": "deny", "read": "ask", "glob": "ask", "grep": "ask", "edit": "ask",
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
    if name == "shell":
        return True  # The entire runtime and its descendants are inside the OS namespace.
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


def split_contract(brief: str) -> tuple[str, str | None]:
    """The turn's task and Kai's contract, split at the contract's heading (its last one: the platform appends the
    contract after everything else, so a heading quoted in an issue stays in the task). None: no contract (an older
    platform), and the brief goes whole."""
    task, found, contract = brief.rpartition("\n" + CONTRACT_HEADING + "\n")
    if not found:
        return brief, None
    return task.rstrip() + "\n", (CONTRACT_HEADING + "\n" + contract).strip()


def emit(kind: str, **values: Any) -> None:
    print(json.dumps({"type": kind, **values}), flush=True)


async def run(profile: Path, browser: Path | None = None, steer_dir: Path | None = None) -> int:
    from .fx_native import available, launch

    if not NATIVE_FX_POLICY_VALIDATED or not available():
        emit("error", message=NATIVE_FX_REFUSAL)
        return 1
    binary = shutil.which("fx")
    if binary is None:
        emit("error", message="The local coding tool is not installed")
        return 1
    brief, contract = split_contract(sys.stdin.read())
    root = Path.cwd().resolve()
    servers = []
    if browser is not None:
        configured = json.loads(browser.read_text())["mcpServers"]["browser"]
        servers = [{"type": "http", "name": "browser", "url": configured["url"],
                    "headers": [{"name": name, "value": value} for name, value in configured["headers"].items()]}]
    configured_browser = json.loads(browser.read_text())["mcpServers"]["browser"] if browser else None
    manager = launch(profile, str(Path(binary).resolve()), root, configured_browser)
    try:
        child, bridge_port = await manager.__aenter__()
    except (OSError, ValueError, TimeoutError):
        emit("error", message="Could not start isolated local execution; use the tested runtime with a custom API-key connection or cloud coding")
        return 1
    if browser:
        servers = [{"type": "http", "name": "browser", "url": f"http://127.0.0.1:{bridge_port}/browser", "headers": []}]
    assert child.stdin and child.stdout
    pending: dict[int, asyncio.Future] = {}
    calls: dict[str, dict] = {}
    counter = 0
    session_id = None
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
                        future.set_exception(RuntimeError(str(value["error"].get("message", "The local turn failed"))))
                    else:
                        future.set_result(value.get("result"))
                elif value.get("method") == "session/update":
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
        # Kai's contract as the session's system profile (ACP's systemPrompt), as on a cloud turn. Each local turn
        # starts a session of its own, so there's no saved profile to keep or check.
        opened = {"cwd": str(root), "mcpServers": servers}
        if contract:
            opened["systemPrompt"] = [{"type": "text", "text": contract}]
        session = await request("session/new", opened)
        session_id = session["sessionId"]
        await request("session/set_mode", {"sessionId": session_id, "modeId": "ask"})
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
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.profile, args.browser_config, args.steer_dir)))


if __name__ == "__main__":
    main()
