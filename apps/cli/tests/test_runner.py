"""`dotrix runner`'s pieces that need no platform: reading the tool's output, and the srt wrapper.
The whole loop runs against the real API in the backend's tests (test_coding.py, local turns)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from dotrix_cli.runner import LocalRunner, Outcome, Tool, parse_line
from dotrix_cli.sandbox import ALLOWED_DOMAINS


def test_claude_codes_stream_becomes_events_and_a_summary() -> None:
    out = Outcome()
    parse_line(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Adding refund()"},
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/pay.py"}},
        {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}},
    ]}}), out)
    parse_line(json.dumps({"type": "result", "subtype": "success", "result": "Done; tests pass.",
                           "total_cost_usd": 0.03, "usage": {"input_tokens": 120, "output_tokens": 40}}), out)
    parse_line("plain text from a wrapper\n", out)
    assert [(e["kind"], e["text"]) for e in out.events] == [
        ("text", "Adding refund()"), ("tool", "Edit src/pay.py"), ("tool", "Bash pytest -q"),
        ("text", "plain text from a wrapper"),
    ]
    assert out.summary == "Done; tests pass." and out.usage == {"input_tokens": 120, "output_tokens": 40, "cost_usd": 0.03}


def test_opencode_events_and_errors() -> None:
    out = Outcome()
    parse_line(json.dumps({"type": "tool_use", "part": {"tool": "edit", "state": {"input": {"path": "a.py"}}}}), out)
    parse_line(json.dumps({"type": "text", "part": {"text": "Changed a.py"}}), out)
    parse_line(json.dumps({"type": "error", "error": {"message": "provider refused"}}), out)
    assert [e["text"] for e in out.events] == ["edit a.py", "Changed a.py", "provider refused"]
    assert out.summary == "Changed a.py"


def test_claude_code_runs_commands_only_inside_the_sandbox() -> None:
    assert "--allowedTools" not in Tool.named("claude-code", isolated=False).argv
    assert Tool.named("claude-code", isolated=True).argv[-2:] == ["--allowedTools", "Bash"]
    assert Tool.named("opencode", isolated=False).argv[:2] == ["opencode", "run"]


def test_srt_writes_only_to_the_worktree_and_reaches_only_model_apis(tmp_path: Path, monkeypatch) -> None:
    from dotrix_cli import sandbox

    monkeypatch.setattr(sandbox, "command", lambda: ["srt"])
    runner = LocalRunner(api=None, repo=tmp_path, workspace_id="w", project_id="p")  # type: ignore[arg-type]
    tree = tmp_path / "trees" / "kun-1-abc123-1"
    tree.mkdir(parents=True)
    argv, leftovers = runner._sandboxed(["claude", "-p"], tree)
    assert leftovers == [] or sandbox.platform.system() == "Windows"
    assert argv[:2] == ["srt", "--settings"] and argv[3:] == ["--", "claude", "-p"]
    settings = json.loads(Path(argv[2]).read_text())
    assert str(tree) in settings["filesystem"]["allowWrite"] and str(tmp_path) not in settings["filesystem"]["allowWrite"]
    assert "~/.ssh" in settings["filesystem"]["denyRead"]
    assert settings["network"]["allowedDomains"] == ALLOWED_DOMAINS and "github.com" not in ALLOWED_DOMAINS
    assert not Path(argv[2]).is_relative_to(tree)  # the settings never land in the worktree (or the patch)


def test_the_sandbox_runtime_comes_with_dotrix(tmp_path: Path, monkeypatch) -> None:
    from dotrix_cli import sandbox

    monkeypatch.setenv("DOTRIX_TOOLS_DIR", str(tmp_path / "tools"))
    monkeypatch.delenv("DOTRIX_SRT", raising=False)
    monkeypatch.delenv("DOTRIX_SRT_NODE", raising=False)
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)  # nothing on this machine
    assert sandbox.command() is None and not sandbox.check().ready
    assert any("Node 22.12" in m for m in sandbox.check().missing)
    try:
        sandbox.install()
        raise AssertionError("installed without npm")
    except RuntimeError as exc:
        assert "Node 22.12" in str(exc)

    # The copy dotrix installed, run with Node directly (no shim, no global install).
    cli = sandbox.installed_cli()
    cli.parent.mkdir(parents=True)
    cli.write_text("// srt")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert sandbox.command() == ["/usr/bin/node", str(cli)] and sandbox.VERSION in str(cli)
    assert sandbox.env() == {}

    # The desktop app's own copy, run by its executable as Node, wins.
    bundled = tmp_path / "app" / "cli.js"
    bundled.parent.mkdir()
    bundled.write_text("// srt")
    monkeypatch.setenv("DOTRIX_SRT", str(bundled))
    monkeypatch.setenv("DOTRIX_SRT_NODE", "/Applications/dotrix.app/dotrix")
    assert sandbox.command() == ["/Applications/dotrix.app/dotrix", str(bundled)]
    assert sandbox.env() == {"ELECTRON_RUN_AS_NODE": "1"}


def test_the_cli_and_the_desktop_app_pin_the_same_sandbox_runtime() -> None:
    from dotrix_cli import sandbox

    desktop = json.loads((Path(__file__).parents[2] / "desktop" / "package.json").read_text())
    assert desktop["dependencies"][sandbox.PACKAGE] == sandbox.VERSION


def test_srt_settings_per_platform(tmp_path: Path) -> None:
    from dotrix_cli import sandbox

    home, tree = tmp_path / "home", tmp_path / "trees" / "t"
    mac = sandbox.settings(tree, home=home, system="Darwin")["filesystem"]["allowWrite"]  # type: ignore[index]
    assert "/private/tmp" in mac and "/tmp" in mac and str(home / ".claude") in mac  # macOS's temp folders too
    win = sandbox.settings(tree, home=home, system="Windows")["filesystem"]["allowWrite"]  # type: ignore[index]
    assert str(tree) in win and "/tmp" not in win and tempfile.gettempdir() not in win  # its own %TEMP%


def test_the_windows_launcher_hands_the_tool_its_environment_and_nothing_else(tmp_path: Path) -> None:
    from dotrix_cli import sandbox

    home = Path("C:/Users/ada")
    launcher = tmp_path / "t.launch.cmd"
    argv = sandbox.windows_launcher(launcher, ["C:/npm/claude.cmd", "-p", "--allowedTools", "Bash"], {
        "ANTHROPIC_API_KEY": "sk-ant-x", "OPENAI_BASE_URL": "https://p/100%", "DOTRIX_TOKEN": "dtx_secret",
        "PATH": "C:/Windows", "AWS_SECRET_ACCESS_KEY": "nope",
    }, home=home)
    assert argv == ["cmd.exe", "/d", "/c", str(launcher)]
    text = launcher.read_bytes().decode()
    assert 'set "ANTHROPIC_API_KEY=sk-ant-x"' in text and 'set "OPENAI_BASE_URL=https://p/100%%"' in text
    assert f'set "CLAUDE_CONFIG_DIR={home / ".claude"}"' in text  # its sign-in, not the sandbox account's
    assert "dtx_secret" not in text and "AWS_SECRET" not in text and "C:/Windows" not in text
    assert '"C:/npm/claude.cmd" "-p" "--allowedTools" "Bash"' in text and text.endswith("exit /b %errorlevel%\r\n")


def test_the_windows_setup_is_read_from_srt_win_status(tmp_path: Path, monkeypatch) -> None:
    import subprocess as sp

    from dotrix_cli import sandbox

    exe = tmp_path / "srt-win.exe"
    exe.write_text("")
    monkeypatch.setattr(sandbox, "srt_win", lambda: exe)

    def answer(payload: dict) -> None:
        monkeypatch.setattr(sandbox.subprocess, "run", lambda *a, **k: sp.CompletedProcess(a, 0, json.dumps(payload), ""))

    answer({"user": {"user": {"exists": False}, "cred_present": False}, "wfp": {"state": "absent"}})
    assert "one administrator prompt" in (sandbox.windows_setup_missing() or "")
    answer({"user": {"user": {"exists": True}, "cred_present": True}, "wfp": {"state": "cannot-read"}})
    assert sandbox.windows_setup_missing() is None  # set up (the filters aren't readable without elevation)
    monkeypatch.setattr(sandbox, "srt_win", lambda: None)
    assert "srt-win.exe" in (sandbox.windows_setup_missing() or "")


def test_on_windows_the_tool_runs_through_the_launcher_and_it_is_removed(tmp_path: Path, monkeypatch) -> None:
    from dotrix_cli import runner as runner_module
    from dotrix_cli import sandbox

    monkeypatch.setattr(sandbox, "command", lambda: ["node", "cli.js"])
    monkeypatch.setattr(runner_module.platform_info, "system", lambda: "Windows")
    tree = tmp_path / "trees" / "kun-1-abc123-1"
    tree.mkdir(parents=True)
    runner = LocalRunner(api=None, repo=tmp_path, workspace_id="w", project_id="p")  # type: ignore[arg-type]
    argv, leftovers = runner._sandboxed(["C:/npm/claude.cmd", "-p"], tree)
    assert argv[:3] == ["node", "cli.js", "--settings"] and argv[4:] == ["--", "cmd.exe", "/d", "/c", str(leftovers[0])]
    assert leftovers[0].exists() and not leftovers[0].is_relative_to(tree)  # never in the worktree (or its patch)
    runner_module._remove(leftovers)
    assert not leftovers[0].exists()
