"""Native Claude shell policy: fail closed, scoped writes, and credential scrubbing."""
import json
from pathlib import Path

import pytest

from dotrix_cli import claude_local
from dotrix_cli.runner import Tool


def test_native_claude_uses_the_namespace_launcher_and_no_saved_policies(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(claude_local, "available", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-key")
    selected = Tool.named("claude-code", model="anthropic:claude-chosen").argv
    assert "dotrix_cli.claude_local" in selected and selected[selected.index("--model") + 1] == "anthropic:claude-chosen"
    monkeypatch.setenv("ANTHROPIC_MODEL", "other-model")
    assert claude_local.connection("anthropic:claude-chosen")[2] == "claude-chosen"
    argv = Tool.named("claude-code", native=True, browser=Path("browser.json")).argv
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "Bash" in argv[argv.index("--tools") + 1].split(",")
    assert "--dangerously-skip-permissions" not in argv and "--strict-mcp-config" in argv
    policy = json.loads(argv[argv.index("--settings") + 1])
    assert policy["disableAllHooks"]
    assert policy["permissions"]["deny"] == ["WebFetch", "WebSearch", "Skill"]
    # Its subagents run in the same namespace: Kai's workers, the one that runs commands too.
    assert "Agent" in argv[argv.index("--tools") + 1].split(",")
    assert set(json.loads(argv[argv.index("--agents") + 1])) == {"explorer", "tester", "reviewer"}
    assert "127.0.0.1:31820/browser" in argv[argv.index("--mcp-config") + 1]
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert "Bash" not in Tool.named("claude-code").argv[Tool.named("claude-code").argv.index("--tools") + 1]


@pytest.mark.parametrize("url", ["http://public.example", "https://user:secret@example.com", "https://example.com?key=secret"])
def test_native_claude_refuses_ambiguous_provider_endpoints(monkeypatch, url):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
    with pytest.raises(ValueError):
        claude_local.connection()


async def test_native_claude_refuses_if_isolation_was_lost(monkeypatch, capsys):
    monkeypatch.setattr(claude_local, "available", lambda: False)
    monkeypatch.setattr("shutil.which", lambda name: "/fake/claude")
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: pytest.fail("Must not start an engine"))
    assert await claude_local.run() == 1
    assert "command isolation is unavailable" in capsys.readouterr().out
