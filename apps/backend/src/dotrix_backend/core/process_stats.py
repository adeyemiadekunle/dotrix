"""What each backend process costs to run, for the admin console's Resources page (`/v1/admin/observe/processes`).

Every API and worker process samples itself every `SAMPLE_SECONDS`: its memory (resident set size, with its child
processes, such as the fx chat host), CPU use since the last sample, threads, open files, uptime, and how long it took
from the process starting to being ready to serve (`ready_seconds`). The latest sample goes to Redis under
`dotrix:proc:latest:<role>:<host>:<pid>:<instance>` (it expires when the process stops sampling) and the last hour of samples
under `dotrix:proc:history:...`, so the console sees every API replica and worker. Without Redis (local jobs), the
console sees only the API process that answers.

Linux (production's containers) is read from /proc. Elsewhere, memory is the process's peak (`ru_maxrss`) and CPU its
own, without children. Nothing here holds anything a person wrote or any secret.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import resource
import socket
import sys
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

SAMPLE_SECONDS = 30
HISTORY = 120  # samples kept per process: an hour at SAMPLE_SECONDS
LATEST = "dotrix:proc:latest:"
HISTORY_KEY = "dotrix:proc:history:"
_LINUX = sys.platform.startswith("linux") and Path("/proc/self/stat").exists()
_TICK = os.sysconf("SC_CLK_TCK") if _LINUX else 100
_PAGE = os.sysconf("SC_PAGE_SIZE") if _LINUX else 4096
Role = Literal["api", "worker"]


class ProcessSample(BaseModel):
    role: Role
    host: str = Field(description="The machine or container the process runs on")
    pid: int
    instance: str = Field(default="", description="A random id per process start: two containers can share a host "
                                                  "name and PID 1")
    revision: str | None = Field(default=None, description="The deployed commit, when set (DOTRIX_DEPLOYMENT_REVISION)")
    python: str
    started_at: datetime = Field(description="When the process started")
    ready_seconds: float | None = Field(default=None, description="From the process starting to ready to serve")
    uptime_seconds: float
    rss_mb: float = Field(description="Resident memory now, with child processes (Linux)")
    peak_rss_mb: float = Field(description="The most resident memory seen since the process started")
    cpu_percent: float = Field(description="CPU since the last sample; 100 is one core busy")
    cpu_seconds: float = Field(description="CPU time used since the process started, with child processes")
    threads: int
    children: int = Field(description="Child processes (the fx chat host, git)")
    open_files: int | None = None
    at: datetime = Field(description="When this sample was taken")


class ProcessPoint(BaseModel):
    at: datetime
    rss_mb: float
    cpu_percent: float


class ProcessRead(ProcessSample):
    history: list[ProcessPoint] = Field(default_factory=list, description="The last hour's samples, oldest first")


class ProcessesRead(BaseModel):
    generated_at: datetime
    shared: bool = Field(description="Whether processes report through Redis (every replica and worker), or only "
                                     "the API process that answered is shown")
    sample_seconds: int = SAMPLE_SECONDS
    processes: list[ProcessRead]


def _tree(pid: int) -> list[int]:
    found, todo = [], [pid]
    while todo:
        current = todo.pop()
        found.append(current)
        with suppress(OSError):
            for task in Path(f"/proc/{current}/task").iterdir():
                todo += [int(child) for child in (task / "children").read_text().split()]
    return sorted(set(found))


def _stat(pid: int) -> list[str] | None:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except OSError:
        return None


def _started_at() -> float:
    """The process's start, as a Unix time: from /proc on Linux, else when this module was imported."""
    if _LINUX:
        with suppress(OSError, ValueError, IndexError):
            fields = _stat(os.getpid())
            boot = next(int(line.split()[1]) for line in Path("/proc/stat").read_text().splitlines()
                        if line.startswith("btime "))
            if fields:
                return boot + int(fields[19]) / _TICK
    return _IMPORTED


_IMPORTED = time.time()


class ProcessStats:
    """One process's sampler. `ready()` marks it ready to serve; `sample()` takes a reading; `run(redis)` publishes
    one every SAMPLE_SECONDS until cancelled."""

    def __init__(self, role: Role, revision: str | None = None) -> None:
        self.role, self.revision = role, revision
        self.pid = os.getpid()
        self.instance = uuid.uuid4().hex[:8]
        self.host = socket.gethostname()
        self.started = _started_at()
        self.ready_seconds: float | None = None
        self.peak = 0.0
        self._last: tuple[float, float] | None = None  # (wall clock, CPU seconds)

    @property
    def key(self) -> str:
        return f"{self.role}:{self.host}:{self.pid}:{self.instance}"

    def ready(self) -> None:
        if self.ready_seconds is None:
            self.ready_seconds = round(max(time.time() - self.started, 0.0), 2)

    def _readings(self) -> tuple[float, float, int, int | None]:
        """(resident MB, CPU seconds, children, open files) for this process and its children."""
        if _LINUX:
            pids = _tree(self.pid)
            rss = cpu = 0.0
            for pid in pids:
                with suppress(OSError, ValueError, IndexError):
                    rss += int(Path(f"/proc/{pid}/statm").read_text().split()[1]) * _PAGE
                fields = _stat(pid)
                if fields:
                    cpu += (int(fields[11]) + int(fields[12])) / _TICK
            files = None
            with suppress(OSError):
                files = len(os.listdir("/proc/self/fd"))
            return rss / 2**20, cpu, len(pids) - 1, files
        usage = resource.getrusage(resource.RUSAGE_SELF)
        peak = usage.ru_maxrss / (2**20 if sys.platform == "darwin" else 2**10)
        return peak, usage.ru_utime + usage.ru_stime, 0, None

    def sample(self, *, advance: bool = True) -> ProcessSample:
        """A reading. `advance=False` (the console's own look) leaves the CPU interval to the publishing loop."""
        now = time.time()
        rss, cpu, children, files = self._readings()
        self.peak = max(self.peak, rss)
        if self._last is None:
            since = max(now - self.started, 1e-6)
            percent = cpu / since * 100
        else:
            percent = (cpu - self._last[1]) / max(now - self._last[0], 1e-6) * 100
        if advance:
            self._last = (now, cpu)
        return ProcessSample(
            role=self.role, host=self.host, pid=self.pid, instance=self.instance, revision=self.revision, python=platform.python_version(),
            started_at=datetime.fromtimestamp(self.started, UTC), ready_seconds=self.ready_seconds,
            uptime_seconds=round(now - self.started, 1), rss_mb=round(rss, 1), peak_rss_mb=round(self.peak, 1),
            cpu_percent=round(max(percent, 0.0), 2), cpu_seconds=round(cpu, 2), threads=_threads(), children=children,
            open_files=files, at=datetime.fromtimestamp(now, UTC),
        )

    async def publish(self, redis: Any) -> ProcessSample:
        sample = self.sample()
        point = json.dumps([sample.at.isoformat(), sample.rss_mb, sample.cpu_percent])
        async with asyncio.timeout(1), redis.pipeline(transaction=False) as pipe:
            pipe.set(LATEST + self.key, sample.model_dump_json(), ex=SAMPLE_SECONDS * 3)
            pipe.rpush(HISTORY_KEY + self.key, point)
            pipe.ltrim(HISTORY_KEY + self.key, -HISTORY, -1)
            pipe.expire(HISTORY_KEY + self.key, SAMPLE_SECONDS * HISTORY + 600)
            await pipe.execute()
        return sample

    async def run(self, redis: Any) -> None:
        """Publish a sample now and every SAMPLE_SECONDS. Redis being away skips a sample, never stops the loop."""
        while True:
            try:
                await self.publish(redis)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a missed sample must never take the process down
                logger.debug("process stats: couldn't publish a sample", exc_info=True)
            await asyncio.sleep(SAMPLE_SECONDS)

    async def withdraw(self, redis: Any) -> None:
        """On a clean shutdown: no longer listed (its history ages out)."""
        with suppress(Exception):
            async with asyncio.timeout(1):
                await redis.delete(LATEST + self.key)


def _threads() -> int:
    if _LINUX:
        with suppress(OSError):
            return len(os.listdir("/proc/self/task"))
    import threading

    return threading.active_count()


async def read_processes(redis: Any, local: ProcessStats | None) -> ProcessesRead:
    """Every process that reported in the last few samples, with its hour of history, workers and APIs alike; or,
    without Redis, the API process answering."""
    found: dict[str, ProcessRead] = {}
    if redis is not None:
        with suppress(Exception):
            keys = [key async for key in redis.scan_iter(match=LATEST + "*", count=200)]
            if keys:
                async with redis.pipeline(transaction=False) as pipe:
                    for key in keys:
                        name = key.decode() if isinstance(key, bytes) else key
                        pipe.get(name)
                        pipe.lrange(HISTORY_KEY + name.removeprefix(LATEST), 0, -1)
                    values = await pipe.execute()
                for latest, history in zip(values[::2], values[1::2], strict=True):
                    if not latest:
                        continue
                    sample = ProcessSample.model_validate_json(latest)
                    points = []
                    for raw in history or []:
                        with suppress(ValueError, TypeError, IndexError):
                            at, rss, cpu = json.loads(raw)
                            points.append(ProcessPoint(at=at, rss_mb=rss, cpu_percent=cpu))
                    found[f"{sample.role}:{sample.host}:{sample.pid}:{sample.instance}"] = ProcessRead(
                        **sample.model_dump(), history=points)
    if local is not None:
        current = local.sample(advance=False)
        key = local.key
        history = found[key].history if key in found else []
        found[key] = ProcessRead(**current.model_dump(), history=history)
    processes = sorted(found.values(), key=lambda p: (p.role, p.host, p.pid))
    return ProcessesRead(generated_at=datetime.now(UTC), shared=redis is not None, processes=processes)
