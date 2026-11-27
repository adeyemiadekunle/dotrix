"""The standalone CLI's entry point runs native Code's bridge, which the frozen build has no Python to run."""
import json
import sys
from pathlib import Path

from dotrix_cli import frozen_entry, fx_bridge, fx_native


def test_the_bridge_command_hands_the_rest_of_the_arguments_to_the_bridge(monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "argv", ["dotrix", "_bridge", "/tmp/relay.sock", "/profile", "/bin/fx", "claude"])
    monkeypatch.setattr(fx_bridge, "main", lambda: seen.append(list(sys.argv)))
    frozen_entry.main()
    # fx_bridge reads its channel from sys.argv[1], as it does when Python runs the file.
    assert seen == [["dotrix", "/tmp/relay.sock", "/profile", "/bin/fx", "claude"]]


def test_the_bridge_command_reports_the_versions_it_requires(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["dotrix", "_bridge", "--version"])
    monkeypatch.setattr(fx_bridge, "main", lambda: (_ for _ in ()).throw(AssertionError("the bridge must not start")))
    frozen_entry.main()
    assert json.loads(capsys.readouterr().out) == {
        "bridge": True, "fx": fx_bridge.KAI_FX_VERSION, "claude": fx_bridge.CLAUDE_CODE_VERSION}


def test_any_other_command_is_the_cli(monkeypatch):
    from dotrix_cli import cli

    ran = []
    monkeypatch.setattr(sys, "argv", ["dotrix", "whoami"])
    monkeypatch.setattr(cli, "app", lambda: ran.append(True))
    frozen_entry.main()
    assert ran == [True]


def test_a_frozen_build_starts_the_bridge_as_its_own_command(monkeypatch):
    helper = Path("/bundle/_internal/dotrix_cli/fx_bridge.py")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/bundle/dotrix")
    assert fx_native.bridge_argv(helper) == ["/bundle/dotrix", "_bridge"]


def test_from_source_python_runs_the_bridge_file(monkeypatch):
    helper = Path("/src/dotrix_cli/fx_bridge.py")
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert fx_native.bridge_argv(helper) == [sys.executable, str(helper)]
