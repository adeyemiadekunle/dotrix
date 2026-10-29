"""The runtime validates host configuration and model policy."""
import json
import os

import pytest

from dotrix_engine.runtimes import (
    AgentRuntimeConfig,
    ModelPolicy,
    ModelSelection,
    RuntimeTool,
    fx_configuration_digest,
)
from dotrix_engine.runtimes.fx import _prepare_local_dir


def test_duplicate_tools_are_rejected():
    async def read(arguments):
        return arguments

    tool = RuntimeTool("read", "Read a document", {"type": "object"}, read)
    with pytest.raises(ValueError):
        AgentRuntimeConfig("orion", "You are Orion", (tool, tool))


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
