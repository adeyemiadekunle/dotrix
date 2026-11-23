"""`dotrix runner`'s pieces that need no platform: reading the tool's output, and what the tool gets.
The whole loop runs against the real API in the backend's tests (test_coding.py, local turns)."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from dotrix_cli.runner import LocalRunner, Outcome, Tool, parse_line


def test_unrelated_host_credentials_do_not_reach_a_tool_process(monkeypatch) -> None:
    import os
    import subprocess
    import sys

    from dotrix_cli.runner import _env

    monkeypatch.setenv("DOTRIX_TOKEN", "synthetic-platform-token")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-cloud-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-github-token")
    monkeypatch.setenv("NPM_TOKEN", "synthetic-registry-token")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.test:8080")
    monkeypatch.setenv("NODE_OPTIONS", "--require /untrusted-hook.js")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-tool-key")
    command = (
        "import json, os; print(json.dumps({k: os.environ.get(k) for k in "
        "['DOTRIX_TOKEN', 'AWS_SECRET_ACCESS_KEY', 'GITHUB_TOKEN', 'NPM_TOKEN', 'ALL_PROXY', 'NODE_OPTIONS', 'ANTHROPIC_API_KEY']}))"
    )
    result = subprocess.run([sys.executable, "-c", command], env=_env(), capture_output=True, text=True, check=True)
    values = json.loads(result.stdout)
    assert values.pop("ANTHROPIC_API_KEY") == "synthetic-tool-key"
    assert all(value is None for value in values.values())
    assert _env()["PATH"] == os.environ["PATH"]


def test_provider_keys_and_settings_are_scoped_to_the_selected_tool() -> None:
    from dotrix_cli.toolenv import tool_environment

    environ = {
        "Path": "tool-bin", "SystemRoot": "windows", "HOME": "home", "XDG_CONFIG_HOME": "config",
        "ANTHROPIC_API_KEY": "anthropic-key", "CLAUDE_CODE_OAUTH_TOKEN": "claude-login",
        "OPENAI_API_KEY": "openai-key", "OPENAI_BASE_URL": "https://provider/100%",
        "CODEX_API_KEY": "codex-key", "CODEX_HOME": "codex-auth",
        "OPENCODE_CONFIG": "opencode.json", "GOOGLE_API_KEY": "google-key", "GOOGLE_GEMINI_BASE_URL": "https://google/",
        "ANTHROPIC_UNRELATED_SECRET": "not-a-tool-setting", "OPENAI_UNRELATED_SECRET": "also-unrelated",
        "ELECTRON_RUN_AS_NODE": "parent-only", "PYTHONPATH": "host-only",
    }
    claude = tool_environment("claude-code", environ)
    assert set(claude) == {"Path", "SystemRoot", "HOME", "XDG_CONFIG_HOME", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"}
    opencode = tool_environment("opencode", environ)
    assert set(opencode) == {
        "Path", "SystemRoot", "HOME", "XDG_CONFIG_HOME", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "OPENAI_BASE_URL", "OPENCODE_CONFIG", "GOOGLE_API_KEY", "GOOGLE_GEMINI_BASE_URL",
    }
    assert set(tool_environment("codex", environ)) == {
        "Path", "SystemRoot", "HOME", "XDG_CONFIG_HOME", "OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_API_KEY", "CODEX_HOME",
    }


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
        ("text", "Adding refund()"), ("tool", "Edited src/pay.py"), ("tool", "Ran pytest -q"),
        ("text", "plain text from a wrapper"),
    ]
    assert out.summary == "Done; tests pass." and out.usage == {"input_tokens": 120, "output_tokens": 40, "cost_usd": 0.03}


def test_opencode_events_and_errors() -> None:
    out = Outcome()
    parse_line(json.dumps({"type": "tool_use", "part": {"tool": "edit", "state": {"input": {"path": "a.py"}}}}), out)
    parse_line(json.dumps({"type": "text", "part": {"text": "Changed a.py"}}), out)
    parse_line(json.dumps({"type": "error", "error": {"message": "provider refused"}}), out)
    assert [e["text"] for e in out.events] == ["Edited a.py", "Changed a.py", "provider refused"]
    assert out.summary == "Changed a.py"


def test_claude_code_edits_files_and_runs_no_commands() -> None:
    """Nothing isolates a local turn, so the tool only reads, searches and edits files in its worktree:
    no Bash (acceptEdits alone would still auto-approve rm, mv and cp), and none of the repository's own
    hooks, permission rules, MCP servers, CLAUDE.md or skills."""
    claude = Tool.named("claude-code").argv
    assert claude[-2:] == ["--permission-mode", "acceptEdits"] and "--allowedTools" not in claude
    tools = claude[claude.index("--tools") + 1].split(",")
    assert sorted(tools) == ["Edit", "Glob", "Grep", "Read", "Write"]
    assert claude[claude.index("--setting-sources") + 1] == "user"
    assert "--strict-mcp-config" in claude and "--mcp-config" not in claude and "--safe-mode" in claude
    assert Tool.named("opencode").argv[:2] == ["opencode", "run"]


def test_claude_code_with_the_desktop_apps_browser_gets_only_its_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The desktop app hands its runner the Browser pane's MCP server (this computer only, behind a token). Claude
    Code then gets the file tools and that server's, still no commands and none of the repository's configuration."""
    from dotrix_cli.runner import browser_tools, describe, write_browser_config

    assert browser_tools({}) is None
    assert browser_tools({"DOTRIX_BROWSER_MCP_URL": "http://127.0.0.1:4411/mcp"}) is None  # no token
    assert browser_tools({"DOTRIX_BROWSER_MCP_URL": "https://evil.example/mcp", "DOTRIX_BROWSER_MCP_TOKEN": "t"}) is None
    pane = browser_tools({"DOTRIX_BROWSER_MCP_URL": "http://127.0.0.1:4411/mcp", "DOTRIX_BROWSER_MCP_TOKEN": "secret"})
    assert pane == ("http://127.0.0.1:4411/mcp", "secret")

    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    config = write_browser_config(*pane)
    assert config.parent == tmp_path and json.loads(config.read_text()) == {
        "mcpServers": {"browser": {"type": "http", "url": "http://127.0.0.1:4411/mcp", "headers": {"Authorization": "Bearer secret"}}},
    }
    if os.name != "nt":
        assert config.stat().st_mode & 0o077 == 0  # the token is this person's only

    claude = Tool.named("claude-code", browser=config).argv
    assert sorted(claude[claude.index("--tools") + 1].split(",")) == ["Edit", "Glob", "Grep", "Read", "Write"]
    assert claude[claude.index("--mcp-config") + 1] == str(config) and "secret" not in " ".join(claude)
    assert claude[claude.index("--allowedTools") + 1] == "mcp__browser"
    assert "--strict-mcp-config" in claude and claude[claude.index("--setting-sources") + 1] == "user"
    # Safe mode would switch the pane's server off: the repository's skills and commands are left out another way.
    assert "--safe-mode" not in claude and "--disable-slash-commands" in claude
    assert "--dangerously-skip-permissions" not in claude
    # In a sandbox the pane isn't offered: the microVM can't reach this computer's server.
    assert "--mcp-config" not in Tool.named("claude-code", isolated=True).argv

    assert describe("mcp__browser__browser_navigate", {"url": "http://localhost:3000/x"}) == "Opened http://localhost:3000/x in the browser"
    assert describe("mcp__browser__browser_click", {"ref": 4}) == "Clicked in the browser"
    assert describe("mcp__browser__app_start", {}) == "Started the app on this computer"


def test_opencode_on_a_turn_nothing_isolates_runs_no_commands() -> None:
    """Checked against OpenCode 2.3.0 with a scripted model: a shell call is refused even when the person's own
    config allows it on an agent, and `fetch` inside `execute` is refused with `webfetch`."""
    from dotrix_cli.runner import opencode_settings

    argv = Tool.named("opencode").argv
    assert argv[:2] == ["opencode", "run"] and "--standalone" in argv and "--auto" in argv
    assert argv[argv.index("--agent") + 1] == "build"
    assert Tool.named("opencode", isolated=True).argv == ["opencode", "run", "--format", "json"]

    mine = json.dumps({"model": "nvidia/x", "permission": {"bash": "allow", "edit": "allow"},
                       "agent": {"build": {"permission": {"bash": {"*": "allow"}}, "model": "nvidia/y"}},
                       "mcp": {"mine": {"type": "remote", "url": "https://example.test/mcp"}}})
    env = opencode_settings({"OPENCODE_CONFIG_CONTENT": mine})
    assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1" and env["OPENCODE_DISABLE_AUTOUPDATE"] == "1"
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    denied = ("bash", "webfetch", "websearch", "question", "subagent", "task", "skill")
    assert all(config["permission"][tool] == "deny" for tool in denied) and config["permission"]["edit"] == "allow"
    assert all(config["agent"]["build"]["permission"][tool] == "deny" for tool in denied)
    assert config["agent"]["build"]["model"] == "nvidia/y" and config["model"] == "nvidia/x"  # the person's own kept
    assert "browser" not in config["mcp"] and config["mcp"]["mine"]["url"] == "https://example.test/mcp"

    with_pane = json.loads(opencode_settings({}, ("http://127.0.0.1:4411/mcp", "secret"))["OPENCODE_CONFIG_CONTENT"])
    assert with_pane["mcp"]["browser"] == {"type": "remote", "url": "http://127.0.0.1:4411/mcp", "headers": {"Authorization": "Bearer secret"}}
    assert json.loads(opencode_settings({"OPENCODE_CONFIG_CONTENT": "not json"})["OPENCODE_CONFIG_CONTENT"])["permission"]["bash"] == "deny"

    from dotrix_cli.runner import describe
    assert describe("execute", {"code": 'return await tools.browser["browser_snapshot"]({})'}) == "Used the browser"
    assert describe("execute", {"code": "return 1 + 1"}) == "Ran a script"


def test_claude_code_in_a_sandbox_still_ignores_the_repositorys_configuration() -> None:
    claude = Tool.named("claude-code", isolated=True).argv
    assert "--dangerously-skip-permissions" in claude and "--tools" not in claude  # it may run commands in the VM
    assert claude[claude.index("--setting-sources") + 1] == "user" and "--strict-mcp-config" in claude


def test_an_older_tool_refusing_an_option_says_to_update_it() -> None:
    from dotrix_cli.runner import _unknown_option

    assert _unknown_option("error: unknown option '--safe-mode'")
    assert not _unknown_option("Invalid API key · Please run /login")



async def test_output_lines_of_any_length_are_read() -> None:
    import asyncio

    from dotrix_cli.runner import MAX_LINE, read_lines

    stream = asyncio.StreamReader()  # its default limit is 64 KiB: `readline` would fail on these
    huge = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 200_000}]}})
    stream.feed_data(huge.encode() + b"\n" + b"y" * (MAX_LINE + 10) + b"\nafter\nlast without an end")
    stream.feed_eof()
    lines: list[str] = []
    await read_lines(stream, lines.append)
    assert lines[0] == huge and len(lines[1]) == MAX_LINE and lines[2:] == ["after", "last without an end"]


def test_each_checkout_registers_as_its_own_runner(tmp_path: Path) -> None:
    (tmp_path / "a" / "api").mkdir(parents=True)
    (tmp_path / "b" / "api").mkdir(parents=True)
    one = LocalRunner(api=None, repo=tmp_path / "a" / "api", workspace_id="w", project_id="p1")  # type: ignore[arg-type]
    two = LocalRunner(api=None, repo=tmp_path / "b" / "api", workspace_id="w", project_id="p2")  # type: ignore[arg-type]
    assert one.name != two.name and "api" in one.name
    assert LocalRunner(api=None, repo=tmp_path, workspace_id="w", project_id="p", name="laptop").name == "laptop"  # type: ignore[arg-type]


async def test_a_turn_for_another_project_is_never_coded_here(tmp_path: Path) -> None:
    posted: list[tuple[str, dict]] = []

    class Api:
        async def post(self, path: str, body=None):
            posted.append((path, body))

    runner = LocalRunner(api=Api(), repo=tmp_path, workspace_id="w", project_id="mine", runner_id="r1")
    await runner.work({"run_id": "run-1", "project_id": "theirs", "lease_token": 1, "lease_seconds": 120,
                       "issue_key": "MOB-1", "turn": 1, "title": "x", "base_branch": "main", "branch": None,
                       "tool": "claude-code", "brief": "x"})
    [(path, body)] = posted
    assert path.endswith("/runs/run-1/result") and body["outcome"] == "failed" and "another project" in body["error"]


async def test_what_the_agent_does_reaches_the_platform_within_seconds(tmp_path: Path, monkeypatch) -> None:
    """The lease is renewed every third of it (40 s by default); events waiting go out every couple
    of seconds anyway, so a local turn's view keeps up like a cloud turn's."""
    import shlex
    import subprocess
    import sys
    import time

    origin = tmp_path / "origin"
    subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
    (origin / "a.txt").write_text("a\n")
    subprocess.run(["git", "-C", str(origin), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(origin), "-c", "user.email=a@b.c", "-c", "user.name=A", "commit", "-qm", "1"], check=True)
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(origin), str(checkout)], check=True)

    started = time.monotonic()
    calls: list[tuple[float, str, dict]] = []
    notified: list[dict] = []

    class Api:
        async def post(self, path: str, body=None):
            calls.append((time.monotonic() - started, path.rsplit("/", 1)[-1], body or {}))
            return {"stop": False}

    monkeypatch.setenv("DOTRIX_TEST_SECRET", "synthetic-host-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-selected-tool-key")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-other-tool-key")
    script = ("import json, os, time; assert 'DOTRIX_TEST_SECRET' not in os.environ; "
              "assert os.environ['ANTHROPIC_API_KEY'] == 'synthetic-selected-tool-key'; "
              "assert 'OPENAI_API_KEY' not in os.environ; "
              "print(json.dumps({'type': 'assistant', 'message': {'content': "
              "[{'type': 'text', 'text': 'Looking at a.txt'}]}}), flush=True); time.sleep(4)")
    runner = LocalRunner(api=Api(), repo=checkout, workspace_id="w", project_id="p", runner_id="r1",
                         command=f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}",
                         worktrees=tmp_path / "trees", echo=lambda _: None, notify=notified.append)
    await runner.work({"run_id": "run-000001", "session_id": "session-1", "project_id": "p", "lease_token": 1, "lease_seconds": 120,
                       "issue_key": "KUN-1", "turn": 1, "title": "x", "base_branch": "main", "branch": None,
                       "tool": "claude-code", "brief": "x"})
    beats = [(at, body) for at, kind, body in calls if kind == "heartbeat"]
    sent = next(at for at, body in beats if any(e["text"] == "Looking at a.txt" for e in body["events"]))
    result = next(at for at, kind, _ in calls if kind == "result")
    # Measure after worktree setup; slow git/filesystem startup is not event-delivery latency.
    assert sent - beats[0][0] < 3.5 and result - sent > 0.5, calls
    # Where the turn's worktree is: to the platform (the desktop app opens it) and to whatever runs this.
    tree = beats[0][1]["worktree"]
    assert Path(tree).is_relative_to(tmp_path / "trees") and notified == [
        {"event": "turn", "run_id": "run-000001", "session_id": "session-1", "issue_key": "KUN-1", "turn": 1, "worktree": tree}]


async def test_a_tool_that_fails_before_changing_anything_is_shown_as_failed(tmp_path: Path) -> None:
    """Not "No changes": the turn failed, and whoever watches the runner sees why."""
    import shlex
    import subprocess
    import sys

    origin = tmp_path / "origin"
    subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
    (origin / "a.txt").write_text("a\n")
    subprocess.run(["git", "-C", str(origin), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(origin), "-c", "user.email=a@b.c", "-c", "user.name=A", "commit", "-qm", "1"], check=True)
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(origin), str(checkout)], check=True)

    results: list[dict] = []
    said: list[str] = []

    class Api:
        async def post(self, path: str, body=None):
            if path.endswith("/result"):
                results.append(body)
            return {"stop": False}

    script = "import sys; sys.stderr.write('claude: not signed in\\n'); sys.exit(3)"
    runner = LocalRunner(api=Api(), repo=checkout, workspace_id="w", project_id="p", runner_id="r1",
                         command=f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}",
                         worktrees=tmp_path / "trees", echo=said.append)
    await runner.work({"run_id": "run-000002", "project_id": "p", "lease_token": 1, "lease_seconds": 120,
                       "issue_key": "KUN-2", "turn": 1, "title": "x", "base_branch": "main", "branch": None,
                       "tool": "claude-code", "brief": "x"})
    [result] = results
    assert result["outcome"] == "failed" and "not signed in" in result["error"]
    assert said[-1] == "  Failed: claude: not signed in"


def test_tool_calls_read_as_a_cloud_turns_do_so_the_terminal_panel_lists_them(tmp_path: Path) -> None:
    """The app's Terminal panel lists a turn's `Ran …` events (web/src/core/kaiWork.ts), and paths
    are shown from the worktree's root, as for a cloud turn (backend coding/tools.py)."""
    out = Outcome(root=tmp_path)
    parse_line(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "pnpm   test\n  --run"}},
        {"type": "tool_use", "name": "Write", "input": {"file_path": str(tmp_path / "src" / "new.ts")}},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "/etc/hosts"}},
        {"type": "tool_use", "name": "TodoWrite", "input": {}},
    ]}}), out)
    parse_line(json.dumps({"type": "tool_use", "part": {"tool": "shell", "state": {"input": {"command": "pytest"}}}}), out)
    assert [e["text"] for e in out.events] == ["Ran pnpm test --run", "Wrote src/new.ts", "Read /etc/hosts", "Ran pytest"]


def test_a_commands_output_is_kept_with_it_for_the_terminal_panel() -> None:
    out = Outcome()
    parse_line(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest -q"}},
        {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "a.py"}},
    ]}}), out)
    parse_line(json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t2", "content": "secret file contents"},
        {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "x" * 20_000 + "\n1 passed"}]},
    ]}}), out)
    parse_line(json.dumps({"type": "tool_use", "part": {"tool": "shell", "callID": "c9", "state": {
        "status": "completed", "input": {"command": "ls"}, "output": "a.py\n", "metadata": {"exit": 2}}}}), out)
    ran, read, output, ls, ls_out = out.events
    assert ran == {"kind": "tool", "text": "Ran pytest -q", "ref": "t1"} and "ref" not in read
    assert output["kind"] == "output" and output["ref"] == "t1" and output["text"].endswith("1 passed")
    assert len(output["text"]) < 8_100 and "characters left out" in output["text"]  # its end kept, not the file read
    assert ls["ref"] == ls_out["ref"] == "c9" and ls_out == {"kind": "output-error", "text": "a.py", "ref": "c9"}


async def test_stopping_the_runner_stops_the_tool_it_started(tmp_path: Path) -> None:
    """The tool runs in a process group of its own: when the runner is cancelled (Ctrl-C, or the
    desktop app stopping it), the tool is stopped too rather than left coding with no one to report it."""
    import asyncio
    import os
    import shlex
    import subprocess
    import sys

    import pytest

    origin = tmp_path / "origin"
    subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
    (origin / "a.txt").write_text("a\n")
    subprocess.run(["git", "-C", str(origin), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(origin), "-c", "user.email=a@b.c", "-c", "user.name=A", "commit", "-qm", "1"], check=True)
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(origin), str(checkout)], check=True)
    pid_file = tmp_path / "tool.pid"

    class Api:
        async def post(self, path: str, body=None):
            return {"stop": False}

    script = f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(60)"
    runner = LocalRunner(api=Api(), repo=checkout, workspace_id="w", project_id="p", runner_id="r1",
                         command=f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}",
                         worktrees=tmp_path / "trees", echo=lambda _: None)
    work = asyncio.create_task(runner.work({
        "run_id": "run-000001", "project_id": "p", "lease_token": 1, "lease_seconds": 120, "issue_key": "KUN-1",
        "turn": 1, "title": "x", "base_branch": "main", "branch": None, "tool": "claude-code", "brief": "x"}))
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text():
            break
        await asyncio.sleep(0.1)
    pid = int(pid_file.read_text())
    work.cancel()
    with pytest.raises(asyncio.CancelledError):
        await work
    await asyncio.sleep(0.2)
    if sys.platform == "win32":
        import csv

        # os.kill(pid, 0) is not a POSIX existence probe on Windows.
        listed = subprocess.run(["tasklist", "/fi", f"PID eq {pid}", "/fo", "csv", "/nh"],
                                capture_output=True, text=True, check=True)
        assert all(row[1] != str(pid) for row in csv.reader(listed.stdout.splitlines()) if len(row) > 1)
    else:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


async def test_old_worktrees_are_removed_but_not_the_one_in_use(tmp_path: Path) -> None:
    """A finished turn's worktree goes once untouched for a few days; recent ones and the one coding stay."""
    import os
    import subprocess
    import time

    checkout = tmp_path / "checkout"
    subprocess.run(["git", "init", "-q", "-b", "main", str(checkout)], check=True)
    (checkout / "a.txt").write_text("a\n")
    subprocess.run(["git", "-C", str(checkout), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(checkout), "-c", "user.email=a@b.c", "-c", "user.name=A", "commit", "-qm", "1"], check=True)
    trees = tmp_path / "trees"
    (trees / "p").mkdir(parents=True)
    old, recent, busy, stray = (trees / "p" / name for name in ("kun-1-old", "kun-2-new", "kun-3-busy", "kun-4-stray"))
    for tree in (old, recent, busy):
        subprocess.run(["git", "-C", str(checkout), "worktree", "add", "-q", "--detach", str(tree), "HEAD"], check=True)
    stray.mkdir()  # git lost track of it
    edited = trees / "p" / "kun-5-edited"
    subprocess.run(["git", "-C", str(checkout), "worktree", "add", "-q", "--detach", str(edited), "HEAD"], check=True)
    week_ago = time.time() - 7 * 86400

    def age(tree: Path) -> None:
        for path in [*tree.rglob("*"), tree]:
            os.utime(path, (week_ago, week_ago), follow_symlinks=False)

    for tree in (old, busy, stray, edited):
        age(tree)
    # Someone edited a file already in an old worktree: its folder's time doesn't change, the file's does.
    (edited / "a.txt").write_text("edited by hand\n")
    (trees / "other-project").mkdir()
    os.utime(trees / "other-project", (week_ago, week_ago))
    managed = trees / ".sessions" / "p"
    managed.mkdir(parents=True)
    age(managed)

    runner = LocalRunner(api=None, repo=checkout, workspace_id="w", project_id="p", worktrees=trees, echo=lambda _: None)
    runner._coding_in = busy
    removed = await runner.clean_worktrees()
    assert sorted(removed) == sorted([old, stray])
    assert recent.is_dir() and busy.is_dir() and (trees / "other-project").is_dir()
    assert managed.is_dir()
    assert (edited / "a.txt").read_text() == "edited by hand\n"
    listed = subprocess.run(["git", "-C", str(checkout), "worktree", "list"], capture_output=True, text=True).stdout
    assert str(old) not in listed and str(recent) in listed


def _checkout(tmp_path: Path, files: dict[str, bytes]) -> Path:
    import subprocess

    origin = tmp_path / "origin"
    subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
    for name, data in files.items():
        (origin / name).write_bytes(data)
    subprocess.run(["git", "-C", str(origin), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(origin), "-c", "user.email=a@b.c", "-c", "user.name=A", "commit", "-qm", "1"], check=True)
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(origin), str(checkout)], check=True)
    return checkout


def _tool(script: str) -> str:
    import shlex
    import sys

    return f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"


_RUN = {"run_id": "run-000003", "project_id": "p", "lease_token": 1, "lease_seconds": 120, "issue_key": "KUN-3",
        "turn": 1, "title": "x", "base_branch": "main", "branch": None, "tool": "claude-code", "brief": "x"}


def _steps(count: int) -> str:
    return (f"import json\nfor i in range({count}):\n print(json.dumps({{'type': 'assistant', 'message': "
            "{'content': [{'type': 'text', 'text': f'step {i}'}]}}), flush=True)\n")


def _texts(calls: list[tuple[str, dict]]) -> list[str]:
    return [e["text"] for _, body in calls for e in body.get("events", [])]


async def _turn(tmp_path: Path, script: str, api, files=None) -> list[str]:
    said: list[str] = []
    runner = LocalRunner(api=api, repo=_checkout(tmp_path, files or {"a.txt": b"a\n"}), workspace_id="w",
                         project_id="p", runner_id="r1", command=_tool(script), worktrees=tmp_path / "trees",
                         echo=said.append)
    await runner.work(dict(_RUN))
    return said


async def test_failed_native_turn_does_not_publish_its_partial_edits(tmp_path, monkeypatch):
    import sys

    results = []

    class Api:
        async def post(self, path, body=None):
            if path.endswith("/result"):
                results.append(body)
            return {"stop": False}

    script = ('import json,sys; open("a.txt", "w").write("partial"); '
              'print(json.dumps({"type":"error","message":"Local policy was not loaded"})); sys.exit(1)')
    monkeypatch.setattr(Tool, "named", lambda *args, **kwargs: Tool("codex", [sys.executable, "-c", script]))
    monkeypatch.setattr("dotrix_cli.runner.found_tools", lambda: [])
    runner = LocalRunner(api=Api(), repo=_checkout(tmp_path, {"a.txt": b"original"}), workspace_id="w",
                         project_id="p", runner_id="r1", tool="codex", isolation="none", worktrees=tmp_path / "trees", echo=lambda _: None)
    await runner.work({**_RUN, "tool": "codex"})
    [result] = results
    assert result["outcome"] == "failed" and result["error"] == "Local policy was not loaded"
    assert not result.get("patch") and not result.get("patch_b64")
    assert (runner.repo / "a.txt").read_text() == "original"


async def test_a_burst_of_steps_all_reach_the_platform_before_the_result(tmp_path: Path) -> None:
    calls: list[tuple[str, dict]] = []

    class Api:
        async def post(self, path: str, body=None):
            calls.append((path.rsplit("/", 1)[-1], body or {}))
            return {"stop": False}

    await _turn(tmp_path, _steps(180), Api())
    texts = [t for t in _texts(calls) if t.startswith("step ")]
    assert texts == [f"step {i}" for i in range(180)]
    assert calls[-1][0] == "result"


async def test_steps_survive_failed_heartbeats(tmp_path: Path) -> None:
    calls: list[tuple[str, dict]] = []
    failures = [3]

    class Api:
        async def post(self, path: str, body=None):
            if path.endswith("/heartbeat") and failures[0] > 0:
                failures[0] -= 1
                raise ConnectionError("down")
            calls.append((path.rsplit("/", 1)[-1], body or {}))
            return {"stop": False}

    await _turn(tmp_path, _steps(180), Api())
    texts = [t for t in _texts(calls) if t.startswith("step ")]
    assert texts == [f"step {i}" for i in range(180)]


async def test_when_the_platform_stays_away_the_result_says_steps_are_missing(tmp_path: Path) -> None:
    calls: list[tuple[str, dict]] = []

    class Api:
        async def post(self, path: str, body=None):
            if path.endswith("/heartbeat"):
                raise ConnectionError("down")
            calls.append((path.rsplit("/", 1)[-1], body or {}))
            return {}

    await _turn(tmp_path, _steps(180), Api())
    [(kind, body)] = calls
    assert kind == "result" and len(body["events"]) <= 50
    assert body["events"][-1]["text"].endswith("earlier steps couldn't be sent")
    assert body["events"][-2]["text"] == "step 179"


async def test_a_change_that_is_not_utf8_text_is_sent_as_exact_bytes(tmp_path: Path) -> None:
    results: list[dict] = []

    class Api:
        async def post(self, path: str, body=None):
            if path.endswith("/result"):
                results.append(body)
            return {"stop": False}

    script = "open('a.txt', 'wb').write('caf\\xe9\\n'.encode('latin-1'))"
    await _turn(tmp_path, script, Api(), {"a.txt": b"a\n"})
    [result] = results
    assert result["outcome"] == "changes" and "patch" not in result
    assert b"+caf\xe9\n" in base64.b64decode(result["patch_b64"], validate=True)


async def test_a_utf8_change_is_still_sent_as_a_patch(tmp_path: Path) -> None:
    results: list[dict] = []

    class Api:
        async def post(self, path: str, body=None):
            if path.endswith("/result"):
                results.append(body)
            return {"stop": False}

    await _turn(tmp_path, "open('a.txt', 'wb').write('caf\\xe9\\n'.encode('utf-8'))", Api())
    [result] = results
    assert result["outcome"] == "changes" and "+café" in result["patch"]
    assert base64.b64decode(result["patch_b64"]).decode() == result["patch"]


def _flaky_runner(tmp_path: Path, errors: list, **kwargs):
    claims: list[int] = []

    class Api:
        async def post(self, path: str, body=None):
            claims.append(1)
            if errors:
                raise errors.pop(0)
            return {"run": None}

    return LocalRunner(api=Api(), repo=tmp_path, workspace_id="w", project_id="p", runner_id="r1", **kwargs), claims


async def _serve_until(runner, stop, monkeypatch, done) -> None:
    import asyncio

    from dotrix_cli import runner as runner_module

    monkeypatch.setattr(runner_module, "BACKOFF_START", 0.01)
    monkeypatch.setattr(runner_module, "BACKOFF_MAX", 0.02)
    task = asyncio.create_task(runner.serve(poll_seconds=0.01, stop=stop))
    for _ in range(500):
        if done() or task.done():
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, 2)


import pytest  # noqa: E402


@pytest.mark.parametrize("status", [0, 503, 429])
async def test_serve_waits_out_a_transient_failure(tmp_path: Path, monkeypatch, status: int) -> None:
    import asyncio

    from dotrix_cli.platform import PlatformError

    errors = [PlatformError(status, "unreachable", "Can't reach"), PlatformError(status, "unreachable", "Can't reach")]
    said: list[str] = []
    events: list[dict] = []
    runner, claims = _flaky_runner(tmp_path, errors, echo=said.append, notify=events.append)
    await _serve_until(runner, asyncio.Event(), monkeypatch, lambda: len(claims) >= 4)
    assert len(claims) >= 4 and not errors
    assert said.count("Can't reach dotrix; trying again…") == 1 and said.count("Connected again") == 1
    assert [e["event"] for e in events if e["event"] in ("offline", "online")] == ["offline", "offline", "online"]
    assert all(e["retry_in"] > 0 for e in events if e["event"] == "offline")


async def test_serve_still_stops_on_an_auth_error(tmp_path: Path, monkeypatch) -> None:
    import asyncio

    import pytest

    from dotrix_cli.platform import PlatformError

    runner, _ = _flaky_runner(tmp_path, [PlatformError(401, "unauthorized", "Signed out")])
    with pytest.raises(PlatformError) as caught:
        await asyncio.wait_for(runner.serve(poll_seconds=0.01), 2)
    assert caught.value.status == 401


async def test_stop_ends_the_wait_between_retries(tmp_path: Path, monkeypatch) -> None:
    import asyncio

    from dotrix_cli import runner as runner_module
    from dotrix_cli.platform import PlatformError

    monkeypatch.setattr(runner_module, "BACKOFF_START", 30.0)
    monkeypatch.setattr(runner_module, "BACKOFF_MAX", 60.0)
    runner, claims = _flaky_runner(tmp_path, [PlatformError(0, "unreachable", "x")] * 5)
    stop = asyncio.Event()
    task = asyncio.create_task(runner.serve(poll_seconds=0.01, stop=stop))
    while not claims:
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, 1)


async def test_a_local_fx_turn_gets_steers_from_the_heartbeat_and_reports_them(tmp_path, monkeypatch):
    """The heartbeat hands the runner a person's message once the driver's inbox is open; the runner drops it there,
    and the driver's reports go back on the next heartbeat and with the result."""
    import asyncio
    import sys

    key = "0196a1b2-0000-7000-8000-000000000001"
    driver = (
        "import json,os,sys,time\n"
        "inbox=sys.argv[sys.argv.index('--steer-dir')+1]; os.makedirs(inbox)\n"
        "print(json.dumps({'type':'steering','open':True}),flush=True)\n"
        "path=os.path.join(inbox,'" + key + ".txt'); end=time.time()+20\n"
        "while not os.path.exists(path) and time.time()<end: time.sleep(0.05)\n"
        "text=open(path).read(); os.remove(path)\n"
        "for state in ('sent','accepted','delivered'): print(json.dumps({'type':'steer','id':'" + key + "','state':state}),flush=True)\n"
        "print(json.dumps({'type':'text','text':'Heard: '+text}),flush=True)\n"
        "os.rmdir(inbox); print(json.dumps({'type':'done','final':'ok','stopReason':'end_turn'}),flush=True)\n"
    )
    beats, results = [], []

    class Api:
        async def post(self, path, body=None):
            if path.endswith("/heartbeat"):
                beats.append(body)
                given = body.get("steering_open") and not any(b.get("steering_open") for b in beats[:-1])
                return {"stop": False, "steers": [{"id": key, "message": "Use the refunds table"}] if given else []}
            if path.endswith("/result"):
                results.append(body)
            return {"stop": False}

    monkeypatch.setattr(Tool, "named", lambda *args, **kwargs: Tool("fx", [sys.executable, "-c", driver]))
    started: list[list[str]] = []
    spawn = asyncio.create_subprocess_exec

    async def recording(*argv, **kwargs):
        started.append(list(argv))
        return await spawn(*argv, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", recording)
    monkeypatch.setattr("dotrix_cli.runner.found_tools", lambda: [])
    monkeypatch.setattr("dotrix_cli.fx_local.NATIVE_FX_POLICY_VALIDATED", True)
    monkeypatch.setattr("dotrix_cli.fx_native.available", lambda: True)
    monkeypatch.setattr("dotrix_cli.fx_local.prepare_profile", lambda *args, **kwargs: None)
    runner = LocalRunner(api=Api(), repo=_checkout(tmp_path, {"a.txt": b"a\n"}), workspace_id="w", project_id="p",
                         runner_id="r1", tool="fx", isolation="none", worktrees=tmp_path / "trees", echo=lambda _: None,
                         beat_seconds=0.1, events_seconds=0.1)
    await runner.work({**_RUN, "tool": "fx"})
    [result] = results
    [argv] = [a for a in started if "--steer-dir" in a]
    assert Path(argv[argv.index("--steer-dir") + 1]).name.endswith(f"-{_RUN['lease_token']}")  # one inbox per lease attempt
    reported = [s["state"] for b in beats for s in b.get("steering") or []] + [s["state"] for s in result.get("steering") or []]
    assert reported == ["sent", "accepted", "delivered"], (beats, result)
    assert any(e["text"] == "Heard: Use the refunds table" for b in beats for e in b["events"]) or any(
        e["text"] == "Heard: Use the refunds table" for e in result["events"])


async def test_managed_local_fx_turn_persists_session_and_resumes_on_follow_up(tmp_path: Path, monkeypatch) -> None:
    import sys
    from uuid import uuid4

    session_id = str(uuid4())
    claims = [
        {"run": {"run_id": "run-1", "session_id": session_id, "project_id": "p", "lease_token": 1, "lease_seconds": 120,
                 "issue_key": "KUN-9", "turn": 1, "title": "x", "base_branch": "main", "branch": None,
                 "tool": "fx", "brief": "First turn", "managed_worktree": True}},
        {"run": {"run_id": "run-2", "session_id": session_id, "project_id": "p", "lease_token": 2, "lease_seconds": 120,
                 "issue_key": "KUN-9", "turn": 2, "title": "x", "base_branch": "main", "branch": None,
                 "tool": "fx", "brief": "Second turn", "managed_worktree": True}},
    ]
    seen_args: list[list[str]] = []

    seen_log = tmp_path / "seen.log"
    fake_driver = (
        "import json, pathlib, sys\n"
        "argv = sys.argv[1:]\n"
        "profile = pathlib.Path(argv[argv.index('--profile') + 1])\n"
        "fx_dir = profile / '.fx'\n"
        f"seen = {str(seen_log)!r}\n"
        "with open(seen, 'a') as f: f.write(json.dumps(argv) + '\\n')\n"
        "if '--resume' in argv:\n"
        "    assert (fx_dir / 'sessions' / 's1.json').read_text() == 'turn-1'\n"
        "    assert json.loads((fx_dir / 'dotrix-session.json').read_text())['fxSession'] == 's1'\n"
        "else:\n"
        "    (fx_dir / 'sessions').mkdir(parents=True, exist_ok=True)\n"
        "    (fx_dir / 'sessions' / 's1.json').write_text('turn-1')\n"
        "    (fx_dir / 'dotrix-session.json').write_text(json.dumps({'fxSession': 's1', 'profileDigest': None}))\n"
        "print(json.dumps({'type': 'done', 'final': 'ok', 'stopReason': 'end_turn'}), flush=True)\n"
    )

    class Api:
        async def post(self, path: str, body=None):
            if path.endswith("/claim?managed_worktrees=true"):
                return claims.pop(0) if claims else {"run": None}
            return {"stop": False}

    def fake_named(name, *, profile=None, **kwargs):
        return Tool(name, [sys.executable, "-c", fake_driver, "--profile", str(profile)])

    monkeypatch.setattr(Tool, "named", fake_named)
    monkeypatch.setattr("dotrix_cli.runner.found_tools", lambda: [])
    monkeypatch.setattr("dotrix_cli.fx_local.NATIVE_FX_POLICY_VALIDATED", True)
    monkeypatch.setattr("dotrix_cli.fx_native.available", lambda: True)
    monkeypatch.setattr("dotrix_cli.fx_local.prepare_profile", lambda p, *args, **kwargs: (p / ".fx").mkdir(parents=True, exist_ok=True))
    runner = LocalRunner(api=Api(), repo=_checkout(tmp_path, {"a.txt": b"a\n"}), workspace_id="w", project_id="p",
                         runner_id="r1", tool="fx", isolation="none", worktrees=tmp_path / "trees", echo=lambda _: None)
    assert await runner.once() is True
    assert (runner.worktrees / ".sessions" / "p" / f"{session_id}.fx-session" / "dotrix-session.json").is_file()
    assert await runner.once() is True
    seen_args = [json.loads(line) for line in (tmp_path / "seen.log").read_text().splitlines()]
    assert "--resume" not in seen_args[0]
    assert "--resume" in seen_args[1]


async def test_managed_worktree_leaves_unpublished_and_interrupted_edits_in_place(tmp_path: Path) -> None:
    from uuid import uuid4

    checkout = _checkout(tmp_path, {"a.txt": b"original\n"})
    calls = []

    class Api:
        async def post(self, path, body=None):
            calls.append((path, body))
            return {"stop": False}

    runner = LocalRunner(api=Api(), repo=checkout, workspace_id="w", project_id="p", runner_id="r1",
                         command=_tool("raise AssertionError('must not run')"), isolation="none",
                         worktrees=tmp_path / "trees", echo=lambda _: None)
    session = str(uuid4())
    tree = runner.worktrees / ".sessions" / "p" / session
    tree.parent.mkdir(parents=True)
    from dotrix_cli.runner import git

    await git(checkout, "worktree", "add", "-q", "--detach", str(tree), "HEAD")
    (tree / "a.txt").write_text("unpublished\n")
    run = {**_RUN, "turn": 2, "session_id": session, "managed_worktree": True}

    await runner.work(run)
    path, body = calls.pop()
    assert path.endswith("/result") and body["outcome"] == "failed"
    assert "unpublished edits" in body["error"]
    assert (tree / "a.txt").read_text() == "unpublished\n"
    assert (checkout / "a.txt").read_text() == "original\n"
    active = tree.with_suffix(".active")
    assert not active.exists()

    active.write_text("previous attempt\n")
    await runner.work({**run, "lease_token": 2})
    path, body = calls.pop()
    assert path.endswith("/result") and body["outcome"] == "failed"
    assert "last turn was interrupted" in body["error"]
    assert active.read_text() == "previous attempt\n"
    assert (tree / "a.txt").read_text() == "unpublished\n"

    active.unlink()
    await git(tree, "restore", "--", "a.txt")
    origin = tmp_path / "origin"
    (origin / "a.txt").write_text("upstream\n")
    await git(origin, "-c", "user.email=a@b.c", "-c", "user.name=A", "commit", "-qam", "Change upstream")
    runner.command = _tool("from pathlib import Path; assert Path('a.txt').read_text() == 'upstream\\n'")
    await runner.work({**run, "lease_token": 3})
    assert calls[-1][1]["outcome"] == "no_changes"
    assert (tree / "a.txt").read_text() == "upstream\n"
    assert (checkout / "a.txt").read_text() == "original\n"


def test_worktree_commands_restore_binary_edits_without_overwriting_an_existing_tree(tmp_path, monkeypatch):
    import shutil
    import subprocess
    from types import SimpleNamespace
    from uuid import uuid4

    from typer.testing import CliRunner

    from dotrix_cli import cli
    from dotrix_cli.sync import LinkState

    repo = _checkout(tmp_path, {"file.bin": b"\0original", ".gitignore": b"ignored*.txt\n", "deleted.txt": b"old"})
    state_dir = tmp_path / "link"
    state_dir.mkdir()
    project_id, session_id = str(uuid4()), str(uuid4())
    LinkState("https://example.invalid", "workspace", project_id, "REPO", "Repository").save(state_dir)
    monkeypatch.setattr(cli, "_resolve_project", lambda _: SimpleNamespace(root_dir=repo, dotrix_dir=state_dir))
    root = tmp_path / "trees"
    tree = root / ".sessions" / project_id / session_id
    tree.parent.mkdir(parents=True)

    def git_at(cwd, *args):
        return subprocess.check_output(["git", "-C", str(cwd), *args])

    def command(action, *args):
        return CliRunner().invoke(cli.app, ["worktree", action, session_id, "--worktrees", str(root), *args])

    git_at(repo, "worktree", "add", "-q", "--detach", str(tree), "HEAD")
    base = git_at(tree, "rev-parse", "HEAD")
    (tree / "file.bin").write_bytes(b"\0updated\xff")
    (tree / "deleted.txt").unlink()
    (tree / "added.txt").write_text("new")
    (tree / "ignored.txt").write_text("ignored local data")
    (tree / "ignored-staged.txt").write_text("staged")
    git_at(tree, "add", "-f", "--", "ignored-staged.txt")
    (tree / "ignored-staged.txt").write_text("edited since staging")
    git_at(tree, "add", "--", "deleted.txt")
    before = git_at(tree, "status", "--porcelain=v1")
    marker = tree.with_suffix(".active")
    marker.write_text("running")
    assert command("snapshot").exit_code != 0
    assert marker.read_text() == "running"
    marker.unlink()

    saved = command("snapshot")
    assert saved.exit_code == 0, saved.output
    assert git_at(tree, "status", "--porcelain=v1") == before
    refused = command("restore")
    assert refused.exit_code != 0 and "already exists" in refused.output
    assert (tree / "file.bin").read_bytes() == b"\0updated\xff"

    shutil.rmtree(tree)  # Simulate a missing folder with its old Git registration still present.
    restored = command("restore")
    assert restored.exit_code == 0, restored.output
    assert git_at(tree, "rev-parse", "HEAD") == base
    assert (tree / "file.bin").read_bytes() == b"\0updated\xff"
    assert (tree / "added.txt").read_text() == "new"
    assert not (tree / "deleted.txt").exists()
    assert not (tree / "ignored.txt").exists()
    assert (tree / "ignored-staged.txt").read_text() == "edited since staging"
    assert git_at(tree, "status", "--porcelain=v1").splitlines() == [
        b"A  added.txt", b"D  deleted.txt", b"M  file.bin", b"A  ignored-staged.txt",
    ]
    assert git_at(repo, "status", "--porcelain=v1") == b""

    assert command("cleanup").exit_code != 0
    assert (tree / "file.bin").read_bytes() == b"\0updated\xff"
    git_at(tree, "reset", "--hard", "HEAD")
    (tree / "ignored.txt").write_text("keep me")
    refused = command("cleanup")
    assert refused.exit_code != 0 and "ignored files" in refused.output
    assert (tree / "ignored.txt").read_text() == "keep me"
    (tree / "ignored.txt").unlink()
    (tree / "untracked.txt").write_text("keep me")
    assert command("cleanup").exit_code != 0
    assert (tree / "untracked.txt").read_text() == "keep me"
    (tree / "untracked.txt").unlink()
    marker.write_text("running")
    assert command("cleanup").exit_code != 0
    marker.unlink()
    cleaned = command("cleanup")
    assert cleaned.exit_code == 0, cleaned.output
    assert not tree.exists()
    restored_clean = command("restore", "--cleanup")
    assert restored_clean.exit_code == 0, restored_clean.output
    assert git_at(tree, "status", "--porcelain=v1") == b""
    assert git_at(tree, "rev-parse", "HEAD") == base
    assert command("cleanup").exit_code == 0
    assert command("restore").exit_code == 0
    assert (tree / "file.bin").read_bytes() == b"\0updated\xff"
