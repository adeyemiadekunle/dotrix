"""libfx chat runtime hosted in a private Node process, with tools in Python."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import itertools
import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlparse

from filelock import FileLock

from .contracts import (
    AgentRuntimeConfig,
    EventHandler,
    RuntimeCapabilities,
    RuntimeEvent,
    RuntimeHandoff,
    RuntimeJournalStore,
    RuntimeToolContext,
    TurnResult,
    UnsupportedRuntimeOperation,
    validate_session,
)

_HOST = Path(__file__).with_name("fx_host")
_LOCAL_METADATA = ".dotrix-fx-runtime.json"
_LOCAL_SESSION = re.compile(r"^wrun_[A-Za-z0-9]+$")


def fx_configuration_digest(
    config: AgentRuntimeConfig, *, model: str, base_url: str | None = None, effort: str | None = None,
    context_window: int = 128_000,
) -> str:
    """Fingerprint the same public settings used to bind a local fx session store.

    The host must separately version its own tool implementations and policies.
    Credentials are deliberately excluded.
    """
    identity = {
        "version": "libfx-0.0.16", "name": config.name, "instructions": config.instructions,
        "model": model, "base_url": base_url, "effort": effort, "context_window": context_window,
        "tools": [{"name": tool.name, "description": tool.description, "schema": tool.input_schema,
                   "idempotent": tool.idempotent, "writes": tool.writes,
                   **({"hands_off": True} if tool.hands_off else {})} for tool in config.tools],
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _prepare_local_dir(path: Path, config: AgentRuntimeConfig, model: str, base_url: str | None, effort: str | None,
                       context_window: int) -> None:
    """Prevent accidental reuse under another runtime configuration; this is not authorization."""
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("The local session directory must be an absolute, non-symlink path")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if os.name == "posix" and (stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.geteuid()):
        raise ValueError("The local session directory must be owned by this user and private")
    digest = fx_configuration_digest(config, model=model, base_url=base_url, effort=effort, context_window=context_window)
    metadata = path / _LOCAL_METADATA
    lock = path / ".dotrix-fx-runtime.lock"
    with FileLock(str(lock), timeout=5):
        if metadata.exists():
            if json.loads(metadata.read_text()) != {"version": 1, "digest": digest}:
                raise ValueError("The local session directory belongs to a different runtime configuration")
        else:
            if any(item != lock for item in path.iterdir()):
                raise ValueError("The local session directory must be empty when first bound")
            descriptor = os.open(metadata, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w") as output:
                json.dump({"version": 1, "digest": digest}, output)


class FxRuntime:
    """Memory, local or host-journal runtime; platform controls remain external."""

    capabilities = RuntimeCapabilities(streaming=True, cancellation=True, steering=True)

    def __init__(self, config: AgentRuntimeConfig, process: asyncio.subprocess.Process, *, local: bool = False,
                 journal: RuntimeJournalStore | None = None, engine_session: str | None = None):
        self.process = process
        durable = local or journal is not None
        self.capabilities = RuntimeCapabilities(persistent_sessions=durable, streaming=True, cancellation=True,
                                                resume=durable, steering=True)
        self._local = local
        self._journal = journal
        self._engine_session = engine_session
        self._tools = {tool.name: tool for tool in config.tools}
        self._sequence = itertools.count(1)
        self._pending: dict[str, asyncio.Future] = {}
        self._events: dict[str, asyncio.Queue] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._active: set[str] = set()
        self._tool_tasks: set[asyncio.Task] = set()
        self._write_lock = asyncio.Lock()
        self._closed = False
        self._reader_task = asyncio.create_task(self._read())

    @classmethod
    async def create(
        cls, config: AgentRuntimeConfig, *, model: str, base_url: str | None = None, api_key: str | None = None,
        effort: str | None = None, context_window: int = 128_000, node: str = "node", local_dir: Path | None = None,
        journal: RuntimeJournalStore | None = None, engine_session: str | None = None,
        ephemeral_engine: bool = False,
    ) -> FxRuntime:
        if base_url is not None:
            parsed = urlparse(base_url)
            if not parsed.hostname or parsed.username or parsed.password or (parsed.scheme != "https" and not (
                parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            )):
                raise ValueError("Provider URL must be HTTPS, or HTTP on localhost, with no embedded credentials")
            if effort:
                raise ValueError("Reasoning effort is not supported by this custom-provider adapter")
        if effort is not None and not effort.strip():
            raise ValueError("Reasoning effort must be nonempty")
        if not model or context_window < 1:
            raise ValueError("Invalid agent name, model, or context window")
        if ephemeral_engine:
            if engine_session is None or journal is not None or local_dir is not None:
                raise ValueError("An ephemeral engine needs a session and cannot use persistent storage")
        elif (journal is None) != (engine_session is None) or (journal is not None and local_dir is not None):
            raise ValueError("A host journal needs exactly one engine session and cannot use local storage")
        if engine_session is not None:
            validate_session(engine_session, "session")
        if not (_HOST / "node_modules" / "libfx").exists():
            raise RuntimeError(f"libfx is not installed; run npm ci --prefix {_HOST}")
        if local_dir is not None:
            local_dir = Path(local_dir)
            await asyncio.to_thread(_prepare_local_dir, local_dir, config, model, base_url, effort, context_window)
        process = await asyncio.create_subprocess_exec(
            node, str(_HOST / "worker.mjs"), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=16 * 1024 * 1024,
        )
        runtime = cls(config, process, local=local_dir is not None, journal=journal, engine_session=engine_session)
        try:
            await runtime._request({
                "op": "init", "name": config.name, "instructions": config.instructions, "model": model,
                "baseUrl": base_url, "apiKey": api_key, "effort": effort, "contextWindow": context_window,
                "localDir": str(local_dir) if local_dir is not None else None,
                "persistence": journal is not None, "ephemeralEngine": ephemeral_engine, "sessionId": engine_session,
                "tools": [{"name": tool.name, "description": tool.description, "inputSchema": tool.input_schema,
                           "idempotent": tool.idempotent, "writes": tool.writes, "handsOff": tool.hands_off}
                          for tool in config.tools],
            })
        except BaseException:
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
            await process.wait()
            runtime._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runtime._reader_task
            raise
        return runtime

    async def _send(self, payload: dict) -> None:
        if self.process.stdin is None or self.process.returncode is not None:
            raise RuntimeError("libfx host is unavailable")
        data = (json.dumps(payload) + "\n").encode()
        async with self._write_lock:
            self.process.stdin.write(data)
            await self.process.stdin.drain()

    async def _request(self, payload: dict, *, session: str = "", on_event: EventHandler | None = None) -> dict:
        if self._reader_task.done():
            raise RuntimeError("libfx host is unavailable")
        request_id = str(next(self._sequence))
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        queue = asyncio.Queue() if on_event is not None else None
        observer = asyncio.create_task(self._observe(queue, session, on_event)) if queue is not None else None
        if queue is not None:
            self._events[request_id] = queue
        try:
            await self._send({**payload, "id": request_id})
            return await future
        finally:
            self._pending.pop(request_id, None)
            self._events.pop(request_id, None)
            if queue is not None and observer is not None:
                queue.put_nowait(None)
                await observer

    async def _observe(self, queue: asyncio.Queue, session: str, handler: EventHandler) -> None:
        while (data := await queue.get()) is not None:
            try:
                await handler(RuntimeEvent(data["type"], session, text=data.get("text", ""), tool=data.get("tool"),
                                           message_id=data.get("messageId")))
            except Exception:
                pass  # observers cannot change agent execution

    async def _tool(self, event: dict) -> None:
        try:
            spec = self._tools[event["name"]]
            if not isinstance(event["args"], dict):
                raise ValueError("Tool arguments must be an object")
            session_id = event.get("sessionId")
            if not isinstance(session_id, str) or session_id not in self._active:
                raise ValueError("Tool call has no active session")
            execution_id = event.get("executionId")
            if not isinstance(execution_id, str) or not execution_id:
                raise ValueError("Tool call has no execution ID")
            if spec.execute_scoped:
                result = await spec.execute_scoped(event["args"], RuntimeToolContext(session_id, execution_id))
            else:
                assert spec.execute is not None
                result = await spec.execute(event["args"])
            if isinstance(result, RuntimeHandoff):
                if self._journal is None or not (spec.hands_off or spec.name == "delegate_tasks"):
                    raise ValueError("Only a durable delegation or approval tool can hand off")
                reply = {"op": "tool_reply", "id": event["id"], "ok": True, "handoff": True}
            else:
                # Check serializability before sending, so a malformed host result fails the tool, not the bridge.
                json.dumps(result)
                reply = {"op": "tool_reply", "id": event["id"], "ok": True, "result": result}
        except Exception:
            reply = {"op": "tool_reply", "id": event.get("id"), "ok": False}
        with contextlib.suppress(BrokenPipeError, ConnectionError, RuntimeError):
            await self._send(reply)

    async def _storage(self, event: dict) -> None:
        try:
            if self._journal is None:
                raise ValueError("No host journal")
            op = event.get("op")
            if op == "load":
                snapshot = await self._journal.load()
                checkpoint = ({"through": snapshot.checkpoint[0], "data": base64.b64encode(snapshot.checkpoint[1]).decode()}
                              if snapshot.checkpoint else None)
                result = {"checkpoint": checkpoint, "records": [
                    {"cursor": cursor, "data": base64.b64encode(data).decode()} for cursor, data in snapshot.records
                ]}
            elif op in ("append", "checkpoint"):
                data = base64.b64decode(event["data"], validate=True)
                if op == "append":
                    result = {"cursor": await self._journal.append(expected=event.get("expected"),
                               idempotency_key=event["idempotencyKey"], data=data)}
                else:
                    await self._journal.save_checkpoint(through=event["through"], data=data)
                    result = {}
            else:
                raise ValueError("Unknown journal operation")
            reply = {"op": "storage_reply", "id": event["id"], "ok": True, "result": result}
        except Exception as exc:
            reply = {"op": "storage_reply", "id": event.get("id"), "ok": False,
                     "fenced": getattr(exc, "code", None) == "runtime_journal_fenced"}
        with contextlib.suppress(BrokenPipeError, ConnectionError, RuntimeError):
            await self._send(reply)

    async def _read(self) -> None:
        assert self.process.stdout is not None
        try:
            while line := await self.process.stdout.readline():
                event = json.loads(line)
                if event.get("kind") == "reply":
                    future = self._pending.get(event.get("id"))
                    if future is not None and not future.done():
                        if "error" in event:
                            future.set_exception(RuntimeError(event["error"]))
                        else:
                            future.set_result(event["result"])
                elif event.get("kind") == "tool":
                    task = asyncio.create_task(self._tool(event))
                    self._tool_tasks.add(task)
                    task.add_done_callback(self._tool_tasks.discard)
                elif event.get("kind") == "storage":
                    task = asyncio.create_task(self._storage(event))
                    self._tool_tasks.add(task)
                    task.add_done_callback(self._tool_tasks.discard)
                elif event.get("kind") == "event" and event.get("id") in self._events:
                    self._events[event["id"]].put_nowait(event["event"])
        except (ValueError, asyncio.LimitOverrunError):
            pass
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("libfx host stopped unexpectedly"))

    async def new_session(self) -> str:
        if self._closed:
            raise RuntimeError("Runtime is closed")
        return (await self._request({"op": "new_session"}))["sessionId"]

    async def prompt(self, session_id: str, message: str, *, on_event: EventHandler | None = None,
                     message_id: str | None = None, rerun_tools: tuple[str, ...] = ()) -> TurnResult:
        if self._closed:
            raise RuntimeError("Runtime is closed")
        validate_session(session_id, message)
        self._validate_local_session(session_id)
        if message_id is not None:
            validate_session(message_id, "message")
        self._validate_rerun_tools(rerun_tools)
        return await self._turn(session_id, {"op": "prompt", "message": message, "messageId": message_id,
                                              "rerunTools": list(rerun_tools)}, on_event)

    async def resume(self, session_id: str, *, on_event: EventHandler | None = None,
                     rerun_tools: tuple[str, ...] = (), message_id: str | None = None,
                     message: str | None = None) -> TurnResult:
        """Resume the turn a stopped process left open. With `message` and `message_id`, a session whose
        turn isn't open (it ended or handed off) enters that turn again by ID, like `prompt`."""
        if self._closed:
            raise RuntimeError("Runtime is closed")
        if not self._local and self._journal is None:
            raise UnsupportedRuntimeOperation("Resume requires explicitly configured local storage or a host journal")
        validate_session(session_id, "resume")
        if message_id is not None:
            validate_session(message_id, "message")
        self._validate_local_session(session_id)
        self._validate_rerun_tools(rerun_tools)
        return await self._turn(session_id, {"op": "resume", "rerunTools": list(rerun_tools),
                                              "messageId": message_id, "message": message}, on_event)

    def _validate_local_session(self, session_id: str) -> None:
        if self._engine_session is not None and session_id != self._engine_session:
            raise ValueError("The journal belongs to a different engine session")
        if self._local and not _LOCAL_SESSION.fullmatch(session_id):
            raise ValueError("Local sessions need an ID returned by new_session()")

    def _validate_rerun_tools(self, names: tuple[str, ...]) -> None:
        if names and self._journal is None:
            raise ValueError("Explicit tool retries require a host journal")
        if any(name not in self._tools or not (self._tools[name].idempotent or self._tools[name].hands_off
                                                or name == "delegate_tasks") for name in names):
            raise ValueError("Only explicitly safe tools can be retried on resume")

    async def _turn(self, session_id: str, command: dict, on_event: EventHandler | None) -> TurnResult:
        async with self._locks.setdefault(session_id, asyncio.Lock()):
            if self._closed:
                raise RuntimeError("Runtime is closed")
            self._active.add(session_id)
            try:
                result = await self._request({**command, "sessionId": session_id}, session=session_id, on_event=on_event)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await asyncio.shield(self._request({"op": "cancel", "sessionId": session_id}))
                raise
            finally:
                self._active.discard(session_id)
        usage = result.get("usage")
        normalized = ({key: usage[source] for key, source in (
            ("input_tokens", "inputTokens"), ("output_tokens", "outputTokens"),
            ("cached_input_tokens", "cacheReadTokens"), ("reasoning_tokens", "reasoningTokens"),
        ) if source in usage} if usage else None)
        return TurnResult(text=result["text"], stop_reason=result["stopReason"], usage=normalized,
                          tools=tuple(result["tools"]), message_id=result.get("messageId"),
                          repeated=result.get("repeated", False), handoff=result.get("handoff"))

    async def steer(self, session_id: str, message: str, *, message_id: str | None = None) -> None:
        if self._closed or session_id not in self._active:
            raise RuntimeError("No active turn to steer")
        if not message.strip():
            raise ValueError("Steering message must be nonempty")
        if message_id is not None:
            validate_session(message_id, "steering")
        await self._request({"op": "steer", "sessionId": session_id, "message": message, "messageId": message_id})

    async def cancel(self, session_id: str) -> None:
        if not self._closed and session_id in self._active:
            await self._request({"op": "cancel", "sessionId": session_id})

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.process.returncode is None and not self._reader_task.done():
                for session_id in list(self._active):
                    await asyncio.wait_for(self._request({"op": "cancel", "sessionId": session_id}), timeout=5)
                await asyncio.wait_for(self._request({"op": "close"}), timeout=5)
        finally:
            if self.process.stdin:
                self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
            await self._reader_task
            for task in self._tool_tasks:
                task.cancel()
            await asyncio.gather(*self._tool_tasks, return_exceptions=True)
