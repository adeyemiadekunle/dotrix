"""Live text of a running agent run, for clients that stream it (server-sent events).

The runner publishes the Project Manager's reply as the model writes it; any number of
subscribers get what's been written so far, then each new piece, then the end. It's
in-process and best effort: the run's saved reply stays the source of truth, and a client
that misses the stream just shows the reply when the run finishes.
"""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

_END = object()


@dataclass
class RunStream:
    text: str = ""
    closed: bool = False
    subscribers: set[asyncio.Queue[object]] = field(default_factory=set)

    def publish(self, delta: str) -> None:
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

    def open(self, run_id: uuid.UUID) -> RunStream:
        stream = self._streams[run_id] = RunStream()
        return stream

    def close(self, run_id: uuid.UUID) -> None:
        stream = self._streams.pop(run_id, None)
        if stream is not None:
            stream.close()

    def active(self, run_id: uuid.UUID) -> bool:
        return run_id in self._streams

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
