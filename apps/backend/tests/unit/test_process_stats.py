"""The backend's own resource samples (core/process_stats.py), for the admin console's Resources page."""
import sys
import time

import pytest

from dotrix_backend.core.process_stats import HISTORY_KEY, LATEST, ProcessStats, read_processes


def test_a_sample_reports_memory_cpu_threads_and_startup() -> None:
    stats = ProcessStats("api", "abc1234")
    assert stats.ready_seconds is None
    stats.ready()
    first = stats.ready_seconds
    stats.ready()  # only the first counts
    assert stats.ready_seconds == first and first is not None and first >= 0
    end = time.process_time() + 0.2
    while time.process_time() < end:  # some CPU to see
        pass
    sample = stats.sample()
    assert sample.role == "api" and sample.revision == "abc1234" and sample.rss_mb > 10
    assert sample.peak_rss_mb >= sample.rss_mb and sample.threads >= 1 and sample.uptime_seconds >= 0
    assert sample.cpu_seconds > 0 and sample.started_at <= sample.at
    if sys.platform.startswith("linux"):
        assert sample.open_files and sample.open_files > 0


def test_the_consoles_own_look_leaves_the_cpu_interval_alone() -> None:
    stats = ProcessStats("worker")
    stats.sample()
    before = stats._last
    stats.sample(advance=False)
    assert stats._last == before


async def test_samples_go_through_redis_with_an_hour_of_history(redis) -> None:
    worker = ProcessStats("worker", None)
    worker.host = f"test-{time.time_ns()}"
    worker.ready()
    try:
        await worker.publish(redis)
        await worker.publish(redis)
        api = ProcessStats("api")
        api.host = worker.host
        found = await read_processes(redis, api)
        mine = [p for p in found.processes if p.host == worker.host]
        assert found.shared and [p.role for p in mine] == ["api", "worker"]
        assert len(mine[1].history) == 2 and mine[1].history[0].rss_mb > 0
        await worker.withdraw(redis)
        found = await read_processes(redis, None)
        assert not [p for p in found.processes if p.host == worker.host]
    finally:
        await redis.delete(LATEST + worker.key, HISTORY_KEY + worker.key)


async def test_without_redis_the_answering_process_is_shown() -> None:
    found = await read_processes(None, ProcessStats("api"))
    assert not found.shared and [p.role for p in found.processes] == ["api"]
    assert (await read_processes(None, None)).processes == []


@pytest.mark.parametrize("role", ["api", "worker"])
def test_the_key_names_the_process(role) -> None:
    stats = ProcessStats(role)
    assert stats.key == f"{role}:{stats.host}:{stats.pid}:{stats.instance}" and len(stats.instance) == 8
    assert ProcessStats(role).key != stats.key  # two containers with the same host name and PID 1
