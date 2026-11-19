"""Stop reaches everything a coding turn started inside the sandbox, not just the engine itself."""
import asyncio
import os
import shutil
import sys
from pathlib import Path

import pytest

from dotrix_backend.modules.coding import sandbox
from dotrix_backend.modules.coding.sandbox import ExecResult, interruptible

pytestmark = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("pgrep"), reason="POSIX shell and procps")


async def _run_here(argv, *, stdin, on_line, timeout, cancel):
    """Like the sandbox's CLI client: stopping it leaves what it started running."""
    process = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                   start_new_session=True)
    waiting = asyncio.ensure_future(process.communicate())
    stopped = asyncio.ensure_future(cancel.wait()) if cancel is not None else None
    done, _ = await asyncio.wait({waiting, *([stopped] if stopped else [])}, return_when=asyncio.FIRST_COMPLETED)
    if waiting not in done:
        return ExecResult(code=None, stdout="", stderr="", cancelled=True)
    if stopped is not None:
        stopped.cancel()
    out, err = waiting.result()
    return ExecResult(code=process.returncode, stdout=out.decode(), stderr=err.decode())


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    status = Path(f"/proc/{pid}/status")
    return not (status.exists() and "State:\tZ" in status.read_text())  # a zombie is gone, just not reaped


async def test_stop_kills_the_turns_whole_process_tree(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sandbox, "TURN_PID", str(tmp_path / "turn.pid"))
    monkeypatch.setattr(sandbox, "STOP_GRACE", 0.5)
    pids = tmp_path / "pids"
    # An engine that ignores SIGINT, with a tool that started a test runner of its own.
    script = (f"trap '' INT; sh -c 'sleep 300 & echo $! >> {pids}; sleep 300 & echo $! >> {pids}; wait' & "
              f"echo $! >> {pids}; wait")
    cancel = asyncio.Event()
    turn = asyncio.ensure_future(interruptible(_run_here, ["sh", "-c", script], stdin=None, on_line=None,
                                               timeout=60, cancel=cancel))
    for _ in range(100):
        if pids.exists() and len(pids.read_text().split()) == 3:
            break
        await asyncio.sleep(0.05)
    started = [int(p) for p in pids.read_text().split()] + [int((tmp_path / "turn.pid").read_text())]
    assert all(_alive(pid) for pid in started)

    cancel.set()
    result = await asyncio.wait_for(turn, 20)
    assert result.cancelled
    for _ in range(40):
        if not any(_alive(pid) for pid in started):
            break
        await asyncio.sleep(0.05)
    assert [pid for pid in started if _alive(pid)] == []
