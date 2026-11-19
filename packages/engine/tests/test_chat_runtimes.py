"""The runtime validates host configuration and model policy."""
import asyncio
import json
import os
from types import SimpleNamespace

import pytest

from dotrix_engine.runtimes import (
    AgentRuntimeConfig,
    DeepAgentsRuntime,
    ModelPolicy,
    ModelSelection,
    RuntimeTool,
    UnsupportedRuntimeOperation,
    fx_configuration_digest,
)
from dotrix_engine.runtimes.fx import _prepare_local_dir
from dotrix_engine.testing import ScriptedChatModel


def test_duplicate_tools_are_rejected():
    async def read(arguments):
        return arguments

    tool = RuntimeTool("read", "Read a document", {"type": "object"}, read)
    with pytest.raises(ValueError):
        AgentRuntimeConfig("orion", "You are Orion", (tool, tool))


async def test_deepagents_capabilities_and_cancellation():
    runtime = DeepAgentsRuntime(AgentRuntimeConfig("orion", "You are Orion"), ScriptedChatModel.of("Answer"))
    session = await runtime.new_session()
    assert runtime.capabilities.streaming and runtime.capabilities.cancellation
    assert not runtime.capabilities.steering and not runtime.capabilities.resume
    with pytest.raises(UnsupportedRuntimeOperation):
        await runtime.resume(session)
    with pytest.raises(UnsupportedRuntimeOperation):
        await runtime.steer(session, "Change direction")
    started = asyncio.Event()

    class SlowGraph:
        async def aget_state(self, config):
            return SimpleNamespace(values={})

        async def astream(self, *args, **kwargs):
            started.set()
            await asyncio.Event().wait()
            yield None

    runtime.graph = SlowGraph()
    turn = asyncio.create_task(runtime.prompt(session, "Question"))
    await started.wait()
    await runtime.cancel(session)
    with pytest.raises(asyncio.CancelledError):
        await turn
    await runtime.close()


def test_model_policy_selects_host_tier_and_rejects_unknown_tiers():
    policy = ModelPolicy(
        tiers={"strong": ModelSelection("strong-model", "high"), "economy": ModelSelection("cheap-model")},
        agents={"project-manager": "strong"}, default="economy",
    )
    assert policy.resolve("project-manager") == ModelSelection("strong-model", "high")
    assert policy.resolve("research").model == "cheap-model"
    assert policy.resolve("research", task_tier="strong").model == "strong-model"
    with pytest.raises(ValueError):
        policy.resolve("research", task_tier="unconfigured")


def test_local_store_is_bound_to_its_agent_and_configuration(tmp_path):
    path = tmp_path / "session-store"
    config = AgentRuntimeConfig("orion", "Private project instructions")
    _prepare_local_dir(path, config, "model-a", None, None, 128_000)
    _prepare_local_dir(path, config, "model-a", None, None, 128_000)
    assert "Private project instructions" not in (path / ".dotrix-fx-runtime.json").read_text()
    assert json.loads((path / ".dotrix-fx-runtime.json").read_text())["digest"] == fx_configuration_digest(
        config, model="model-a")
    with pytest.raises(ValueError, match="different runtime configuration"):
        _prepare_local_dir(path, config, "model-b", None, None, 128_000)
    with pytest.raises(ValueError, match="different runtime configuration"):
        _prepare_local_dir(path, AgentRuntimeConfig("vega", "Private project instructions"), "model-a", None, None, 128_000)


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory permissions")
def test_local_store_refuses_shared_directory(tmp_path):
    path = tmp_path / "shared"
    path.mkdir(mode=0o755)
    path.chmod(0o755)
    with pytest.raises(ValueError, match="private"):
        _prepare_local_dir(path, AgentRuntimeConfig("orion", "Instructions"), "model", None, None, 128_000)


def _host(tmp_path, declared, installed=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"libfx": declared}}))
    if installed is not None:
        (tmp_path / "node_modules" / "libfx").mkdir(parents=True)
        (tmp_path / "node_modules" / "libfx" / "package.json").write_text(json.dumps({"version": installed}))
    return tmp_path


def test_the_fx_host_runs_only_an_admitted_libfx_artifact(tmp_path):
    from dotrix_engine.runtimes.fx import LIBFX_ARTIFACTS, installed_libfx_version, libfx_version

    assert libfx_version() in LIBFX_ARTIFACTS  # the repository's own pin is admitted
    assert libfx_version(_host(tmp_path / "pinned", "0.0.16")) == "0.0.16"
    with pytest.raises(RuntimeError, match="not an admitted"):
        libfx_version(_host(tmp_path / "unknown", "9.9.9"))
    assert installed_libfx_version(_host(tmp_path / "absent", "0.0.16")) is None
    assert installed_libfx_version(_host(tmp_path / "other", "0.0.16", installed="0.0.17")) == "0.0.17"


async def test_the_fx_host_refuses_an_install_that_differs_from_its_pin(tmp_path, monkeypatch):
    from dotrix_engine.runtimes import FxRuntime
    from dotrix_engine.runtimes import fx as fx_module

    monkeypatch.setattr(fx_module, "_HOST", _host(tmp_path, "0.0.16", installed="0.0.17"))
    with pytest.raises(RuntimeError, match="0.0.17 is installed but this host pins 0.0.16"):
        await FxRuntime.create(AgentRuntimeConfig("nova", "Answer.", ()), model="test-model")


def test_the_configuration_digest_names_the_pinned_artifact(monkeypatch):
    from dotrix_engine.runtimes import fx as fx_module

    config = AgentRuntimeConfig("nova", "Answer.", ())
    pinned = fx_configuration_digest(config, model="m")
    monkeypatch.setitem(fx_module.LIBFX_ARTIFACTS, "0.0.17-test", ("0.0.16",))
    monkeypatch.setattr(fx_module, "libfx_version", lambda host=None: "0.0.17-test")
    assert fx_configuration_digest(config, model="m") != pinned
