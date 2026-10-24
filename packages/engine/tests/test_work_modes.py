"""Work modes: each has its guidance for the agent talking to the person; an unknown one fails."""
import pytest

from dotrix_engine.agent import build_team
from dotrix_engine.testing import ScriptedChatModel
from dotrix_engine.work_modes import WORK_MODES, guide


def test_each_mode_has_its_guidance() -> None:
    for mode in WORK_MODES:
        assert f"## Mode: {mode.capitalize()}" in guide(mode)
    with pytest.raises(ValueError, match="Unknown work mode"):
        guide("deploy")


def test_build_team_refuses_an_unknown_work_mode() -> None:
    from deepagents.backends import StateBackend

    with pytest.raises(ValueError, match="Unknown work mode"):
        build_team("P", "", ScriptedChatModel.of("hi"), StateBackend, work_mode="deploy")
