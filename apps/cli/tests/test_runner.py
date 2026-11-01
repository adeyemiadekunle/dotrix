"""`dotrix runner`'s pieces that need no platform: reading the tool's output, and what the tool gets.
The whole loop runs against the real API in the backend's tests (test_coding.py, local turns)."""
from __future__ import annotations

import json
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
    """Nothing isolates a local turn, so the tool only edits files in its worktree."""
    claude = Tool.named("claude-code").argv
    assert claude[-2:] == ["--permission-mode", "acceptEdits"] and "--allowedTools" not in claude
    assert Tool.named("opencode").argv[:2] == ["opencode", "run"]



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
    await runner.work({"run_id": "run-000001", "project_id": "p", "lease_token": 1, "lease_seconds": 120,
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
        {"event": "turn", "run_id": "run-000001", "issue_key": "KUN-1", "turn": 1, "worktree": tree}]


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
    week_ago = time.time() - 7 * 86400
    for tree in (old, busy, stray):
        os.utime(tree, (week_ago, week_ago))
    (trees / "other-project").mkdir()
    os.utime(trees / "other-project", (week_ago, week_ago))

    runner = LocalRunner(api=None, repo=checkout, workspace_id="w", project_id="p", worktrees=trees, echo=lambda _: None)
    runner._coding_in = busy
    removed = await runner.clean_worktrees()
    assert sorted(removed) == sorted([old, stray])
    assert recent.is_dir() and busy.is_dir() and (trees / "other-project").is_dir()
    listed = subprocess.run(["git", "-C", str(checkout), "worktree", "list"], capture_output=True, text=True).stdout
    assert str(old) not in listed and str(recent) in listed
