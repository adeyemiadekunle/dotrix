"""Cancellation and output redaction at the cloud environment execution boundary."""
import asyncio
from types import SimpleNamespace

import pytest

from dotrix_backend.modules.coding.runner import CodingWorker, RunFailed, _Stopped
from dotrix_backend.modules.coding.sandbox import ExecResult


async def test_stop_cancels_setup_and_does_not_forward_command_output(monkeypatch):
    monkeypatch.setattr("dotrix_backend.modules.coding.runner.STOP_POLL_SECONDS", 0.001)
    events = []

    async def update(*args, **kwargs):
        events.append(kwargs)

    async def no(*args):
        return False

    async def yes(*args):
        return True

    async def execute(*args, cancel, **kwargs):
        await asyncio.wait_for(cancel.wait(), 1)
        return ExecResult(1, "credential-marker", "credential-marker", cancelled=True)

    worker = SimpleNamespace(_update=update, reconciliation_required=no, stop_requested=yes)
    with pytest.raises(_Stopped, match="setup stopped"):
        await CodingWorker._environment_phase(worker, "run", SimpleNamespace(exec=execute),
            {"revision": 1, "enabled": True, "setup_script": "sleep 60"}, "setup_script")
    assert "credential-marker" not in str(events)


async def test_timeout_is_a_failure_and_output_is_not_in_the_error():
    async def update(*args, **kwargs):
        pass

    async def execute(*args, **kwargs):
        return ExecResult(1, "credential-marker", "credential-marker", timed_out=True)

    with pytest.raises(RunFailed, match="time limit") as caught:
        await CodingWorker._environment_phase(SimpleNamespace(_update=update), "run", SimpleNamespace(exec=execute),
            {"revision": 1, "setup_script": "sleep 60"}, "setup_script")
    assert "credential-marker" not in str(caught.value)


async def test_pinning_an_image_does_not_mutate_the_shared_sandbox_factory():
    from dotrix_backend.core.settings import Settings
    from dotrix_backend.modules.coding.sandbox import OpenShellSandbox

    sandbox = OpenShellSandbox(Settings(database_url="postgresql+asyncpg://localhost/unused",
        jwt_secret="test-only-secret-long-enough-for-settings", coding_image="dotrix-coding:latest"))
    reviewed = "reviewed/image@sha256:" + "b" * 64
    pinned = await sandbox.pin_image(reviewed)
    assert pinned is not sandbox and pinned.image == reviewed  # a digest is already immutable
    assert sandbox.image == "dotrix-coding:latest"