"""Live text of a running agent run, for clients that stream it (server-sent events).

The runner publishes the Project Manager's reply as the model writes it; any number of
subscribers get what's been written so far, then each new piece, then the end. Best effort:
the run's saved reply stays the source of truth, and a client that misses the stream just
shows the reply when the run finishes.

Two implementations with the same interface:
- `RunStreams`: in-process, when runs execute in the API process (or inline in tests).
- `RedisRunStreams`: through Redis, when runs execute in the worker and the API serves
  the stream (a separate process).
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

_END = object()
TTL_SECONDS = 3600  # a stream's keys outlive any run


class Stream(Protocol):
    async def publish(self, delta: str) -> None: ...


class Streams(Protocol):
    async def open(self, run_id: uuid.UUID) -> Stream: ...
    async def close(self, run_id: uuid.UUID) -> None: ...
    def follow(self, run_id: uuid.UUID, heartbeat_seconds: float = 15) -> AsyncIterator[tuple[str, str]]: ...


# -- in process ---------------------------------------------------------------------------


@dataclass
class RunStream:
    text: str = ""
    closed: bool = False
    subscribers: set[asyncio.Queue[object]] = field(default_factory=set)

    async def publish(self, delta: str) -> None:
        if not delta or self.closed:
            return
        self.text += delta
        for queue in self.subscribers:
            queue.put_nowait(delta)

    def close(self) -> None:
        self.closed = True
        for queue in self.subscribers:
            queue.put_nowait(_END)


class RunStreams:
    """One stream per run while it executes (a resumed run gets a fresh one)."""

    def __init__(self) -> None:
        self._streams: dict[uuid.UUID, RunStream] = {}

    async def open(self, run_id: uuid.UUID) -> RunStream:
        stream = self._streams[run_id] = RunStream()
        return stream

    async def close(self, run_id: uuid.UUID) -> None:
        stream = self._streams.pop(run_id, None)
        if stream is not None:
            stream.close()

    async def follow(self, run_id: uuid.UUID, heartbeat_seconds: float = 15) -> AsyncIterator[tuple[str, str]]:
        """Yield ("text", everything so far), then ("delta", piece)…, then ("end", "").
        Heartbeats ("ping", "") keep idle connections open through proxies."""
        stream = self._streams.get(run_id)
        if stream is None:
            yield ("end", "")
            return
        queue: asyncio.Queue[object] = asyncio.Queue()
        stream.subscribers.add(queue)
        try:
            yield ("text", stream.text)
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), heartbeat_seconds)
                except TimeoutError:
                    yield ("ping", "")
                    continue
                if item is _END:
                    break
                yield ("delta", str(item))
            yield ("end", "")
        finally:
            stream.subscribers.discard(queue)


# -- through Redis ------------------------------------------------------------------------


class RedisRunStream:
    def __init__(self, redis: Any, keys: _Keys) -> None:
        self.redis, self.keys = redis, keys

    async def publish(self, delta: str) -> None:
        if not delta:
            return
        # APPEND returns the new length (bytes): followers use it to skip what their
        # snapshot already contains.
        end = await self.redis.append(self.keys.text, delta.encode())
        await self.redis.publish(self.keys.channel, json.dumps({"end": end, "text": delta}))


@dataclass(frozen=True)
class _Keys:
    text: str
    active: str
    channel: str


class RedisRunStreams:
    def __init__(self, redis: Any, prefix: str = "pmagent:stream") -> None:
        self.redis, self.prefix = redis, prefix

    def _keys(self, run_id: uuid.UUID) -> _Keys:
        base = f"{self.prefix}:{run_id}"
        return _Keys(text=f"{base}:text", active=f"{base}:active", channel=f"{base}:events")

    async def open(self, run_id: uuid.UUID) -> RedisRunStream:
        keys = self._keys(run_id)
        pipe = self.redis.pipeline()
        pipe.delete(keys.text)
        pipe.set(keys.text, b"", ex=TTL_SECONDS)
        pipe.set(keys.active, b"1", ex=TTL_SECONDS)
        await pipe.execute()
        return RedisRunStream(self.redis, keys)

    async def close(self, run_id: uuid.UUID) -> None:
        keys = self._keys(run_id)
        await self.redis.delete(keys.active)
        await self.redis.expire(keys.text, 60)
        await self.redis.publish(keys.channel, json.dumps({"end": -1}))

    async def follow(self, run_id: uuid.UUID, heartbeat_seconds: float = 15) -> AsyncIterator[tuple[str, str]]:
        keys = self._keys(run_id)
        pubsub = self.redis.pubsub()
        # Subscribe before reading the snapshot, so nothing written in between is missed.
        await pubsub.subscribe(keys.channel)
        try:
            if not await self.redis.exists(keys.active):
                yield ("end", "")
                return
            snapshot = await self.redis.get(keys.text) or b""
            position = len(snapshot)
            yield ("text", snapshot.decode(errors="replace"))
            loop = asyncio.get_running_loop()
            quiet_since = loop.time()
            while True:
                # get_message returns None for its own subscribe confirmations too, so a None
                # isn't necessarily a quiet second: only ping once the heartbeat interval passes.
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=min(1.0, heartbeat_seconds)
                )
                if message is None:
                    if loop.time() - quiet_since < heartbeat_seconds:
                        continue
                    quiet_since = loop.time()
                    if not await self.redis.exists(keys.active):
                        break  # the end message was missed (or the worker died)
                    yield ("ping", "")
                    continue
                quiet_since = loop.time()
                event = json.loads(message["data"])
                if event["end"] == -1:
                    break
                if event["end"] <= position:
                    continue  # already in the snapshot
                position = event["end"]
                yield ("delta", event["text"])
            yield ("end", "")
        finally:
            await pubsub.unsubscribe(keys.channel)
            await pubsub.aclose()


def text_of(content: object) -> str:
    """The visible text of a message chunk: a string, or the text blocks of a list (skipping
    thinking and tool-call blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content if isinstance(block, dict) and block.get("type", "text") == "text"
        )
    return ""
