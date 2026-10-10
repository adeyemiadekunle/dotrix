"""The warm pool: at most so many sandboxes per workspace (the least recently used closes first),
idle ones found for closing, and a limit of 0 keeping none."""
import uuid

from dotrix_backend.modules.coding.sandbox import ExecResult
from dotrix_backend.modules.coding.warm import WarmPool


class Box:
    def __init__(self) -> None:
        self.closed = False

    async def exec(self, argv, **_) -> ExecResult:
        return ExecResult(code=0, stdout="", stderr="")

    async def close(self) -> None:
        self.closed = True


async def test_the_pool_keeps_a_few_per_workspace_and_closes_the_oldest() -> None:
    pool = WarmPool(idle_seconds=3600, per_workspace=2)
    acme, other = uuid.uuid4(), uuid.uuid4()
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    boxes = {s: Box() for s in (a, b, c, d)}
    assert await pool.put(a, acme, boxes[a]) == []
    assert await pool.put(b, acme, boxes[b]) == []
    assert await pool.put(d, other, boxes[d]) == []  # another workspace's limit is its own
    assert await pool.put(c, acme, boxes[c]) == [a] and boxes[a].closed  # the least recently used goes
    assert set(pool.sessions()) == {b, c, d}
    assert pool.take(b) is boxes[b] and pool.take(b) is None  # taken for a turn: out of the pool
    assert pool.idle() == []


async def test_idle_sandboxes_are_found_and_a_limit_of_zero_keeps_none() -> None:
    pool = WarmPool(idle_seconds=0, per_workspace=3)
    s = uuid.uuid4()
    await pool.put(s, uuid.uuid4(), Box())
    assert pool.idle() == [s]
    assert await pool.close(s) and pool.sessions() == []
    none = WarmPool(idle_seconds=3600, per_workspace=0)
    box = Box()
    assert await none.put(s, uuid.uuid4(), box) == [s] and box.closed and none.sessions() == []
