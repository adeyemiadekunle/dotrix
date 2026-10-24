"""What a machine gives coding runs: how many work at once (RunSlots), and each Docker sandbox's
memory, CPUs, and container runtime."""
import asyncio
import uuid
from pathlib import Path

import pytest

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.coding.sandbox import DockerSandbox
from dotrix_backend.modules.coding.slots import RunSlots, Stopped
from dotrix_backend.modules.coding.tools import ClaudeCode


def _settings(**values) -> Settings:
    base = {"database_url": "postgresql+asyncpg://localhost/unused", "jwt_secret": "x" * 40}
    return Settings(**{**base, **values})  # type: ignore[arg-type]


async def _never_stopped() -> bool:
    return False


async def test_without_a_limit_runs_never_wait() -> None:
    slots, waited = RunSlots(0), []

    async def wait() -> None:
        waited.append(True)

    async with slots.take(on_wait=wait, stopped=_never_stopped), slots.take(on_wait=wait, stopped=_never_stopped):
        pass
    assert waited == []


async def test_a_run_past_the_limit_waits_for_a_free_sandbox_and_says_so() -> None:
    slots, order = RunSlots(1, poll_seconds=0.01), []

    async def run(name: str, hold: asyncio.Event | None = None) -> None:
        async def wait() -> None:
            order.append(f"{name} waits")

        async with slots.take(on_wait=wait, stopped=_never_stopped):
            order.append(f"{name} works")
            if hold is not None:
                await hold.wait()

    hold = asyncio.Event()
    first = asyncio.create_task(run("a", hold))
    await asyncio.sleep(0.01)
    second = asyncio.create_task(run("b"))
    await asyncio.sleep(0.05)
    assert order == ["a works", "b waits"]
    hold.set()
    await asyncio.gather(first, second)
    assert order == ["a works", "b waits", "b works"]


async def test_a_waiting_run_can_be_stopped_and_frees_nothing_it_never_had() -> None:
    slots, stop = RunSlots(1, poll_seconds=0.01), asyncio.Event()

    async def stopped() -> bool:
        return stop.is_set()

    async def nothing() -> None:
        return None

    async with slots.take(on_wait=nothing, stopped=_never_stopped):
        waiting = asyncio.create_task(slots.take(on_wait=nothing, stopped=stopped).__aenter__())
        await asyncio.sleep(0.03)
        stop.set()
        with pytest.raises(Stopped):
            await waiting
    async with slots.take(on_wait=nothing, stopped=_never_stopped):  # the one slot is free again
        pass


async def test_the_docker_sandbox_uses_the_machine_s_limits_and_runtime(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x")
    calls: list[list[str]] = []

    async def cli(self, *args: str, **_: object) -> str:
        calls.append(list(args))
        return ""

    sandbox = DockerSandbox(_settings(coding_memory="3g", coding_cpus=1.5, coding_docker_runtime="runsc"))
    DockerSandbox.cli = cli  # type: ignore[method-assign]
    try:
        await sandbox.open(uuid.uuid4(), tmp_path, ClaudeCode(), "sk-test")
    finally:
        del DockerSandbox.cli
    [agent] = [c for c in calls if c[0] == "run" and "--init" in c]
    assert agent[agent.index("--memory") + 1] == "3g" and agent[agent.index("--cpus") + 1] == "1.5"
    assert agent[agent.index("--runtime") + 1] == "runsc"
    assert "sk-test" not in " ".join(agent)  # the key goes by name, never on argv
    plain = DockerSandbox(_settings())
    assert (plain.memory, plain.cpus, plain.runtime) == ("4g", 2.0, None)  # unchanged defaults
