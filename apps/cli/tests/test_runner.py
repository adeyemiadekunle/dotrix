"""`dotrix runner`'s pieces that need no platform: reading the tool's output, and the srt wrapper.
The whole loop runs against the real API in the backend's tests (test_coding.py, local turns)."""
from __future__ import annotations

import json
from pathlib import Path

from dotrix_cli.runner import ALLOWED_DOMAINS, LocalRunner, Outcome, Tool, parse_line


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
    argv = runner._sandboxed(["claude", "-p"], tree)
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
