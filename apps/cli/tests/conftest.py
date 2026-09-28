"""Shared CLI test fixtures: a fake platform, a link to it, and a linked working copy."""
from __future__ import annotations

import functools
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fake_platform import PID, WS, FakePlatform  # noqa: E402

from pmagent_cli import cli as cli_module  # noqa: E402
from pmagent_cli.agent_client import PlatformAgent  # noqa: E402
from pmagent_cli.sync import LinkState  # noqa: E402
from pmagent_engine.config import ProjectConfig  # noqa: E402


@pytest.fixture
def platform() -> FakePlatform:
    return FakePlatform()


@pytest.fixture
def state() -> LinkState:
    return LinkState(api_url="http://fake", workspace_id=WS, project_id=PID, project_key="KUN", project_name="Kunemi")


@pytest.fixture
def linked_repo(tmp_path: Path, state: LinkState, platform: FakePlatform, monkeypatch) -> Path:
    """A working copy linked to the fake platform, signed in, with polling that doesn't sleep."""
    config = ProjectConfig(name="Kunemi", root_dir=str(tmp_path))
    Path(config.pmagent_dir).mkdir()
    config.save()
    state.save(config.pmagent_dir)
    monkeypatch.setattr(cli_module.PlatformClient, "signed_in", classmethod(lambda cls, url=None, store=None: platform.client()))
    monkeypatch.setattr(cli_module, "PlatformAgent", functools.partial(PlatformAgent, sleep=lambda s: None))
    return tmp_path
