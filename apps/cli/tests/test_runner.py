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


def test_srt_writes_only_to_the_worktree_and_reaches_only_model_apis(tmp_path: Path) -> None:
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
