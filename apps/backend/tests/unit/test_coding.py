"""Coding runs' pure parts: reading Claude Code's and Codex's JSON events, choosing the tool by
the key the server has, what a run's changes may not touch, and stopping a process."""
import asyncio
import json
import sys
import uuid

from pydantic import SecretStr

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.coding import guard
from dotrix_backend.modules.coding.models import CodingAgent
from dotrix_backend.modules.coding.sandbox import run_process, sandbox_policy
from dotrix_backend.modules.coding.tools import (
    OPENCODE_PROVIDERS,
    TOOLS,
    ClaudeCode,
    Codex,
    OpenCode,
    Usage,
    choose_agent,
    model_for,
    opencode_session,
    tool_for,
)


def _settings(**values) -> Settings:
    base = {"database_url": "postgresql+asyncpg://localhost/unused", "jwt_secret": "x" * 40,
            "anthropic_api_key": None, "openai_api_key": None}
    return Settings(**{**base, **values})  # type: ignore[arg-type]


def test_claude_code_events_become_steps_and_tokens() -> None:
    tool, usage = ClaudeCode(), Usage()
    lines = [
        {"type": "system", "subtype": "init", "model": "claude-opus-5-5"},
        # One model call, its blocks as separate events with the same usage: counted once.
        {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "Looking."}],
                                          "usage": {"input_tokens": 100, "cache_read_input_tokens": 900,
                                                    "output_tokens": 50}}},
        {"type": "assistant", "message": {"id": "m1", "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}}],
            "usage": {"input_tokens": 100, "cache_read_input_tokens": 900, "output_tokens": 50}}},
        {"type": "assistant", "message": {"id": "m2", "content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/sandbox/repo/src/a.py"}},
            {"type": "tool_use", "name": "TodoWrite", "input": {}}],
            "usage": {"input_tokens": 10, "output_tokens": 5}}},
    ]
    steps = [s for line in lines for s in tool.parse(json.dumps(line), usage).steps]
    assert [(s.kind, s.text) for s in steps] == [
        ("step", "Claude Code started (claude-opus-5-5)"), ("text", "Looking."), ("tool", "Ran pytest -q"),
        ("tool", "Edited src/a.py"),
    ]
    assert (usage.input_tokens, usage.output_tokens) == (1010, 55)
    done = tool.parse(json.dumps({"type": "result", "subtype": "success", "result": "Done: added a.",
                                  "total_cost_usd": 0.5, "usage": {"input_tokens": 2000, "output_tokens": 60}}), usage)
    assert done.summary == "Done: added a." and usage.total == 2060 and usage.cost_usd == 0.5
    failed = tool.parse(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True}), usage)
    assert failed.failed == "error_max_turns"
    assert tool.parse("not json", usage).steps == []
    retry = {"type": "system", "subtype": "api_retry", "attempt": 1, "error_status": 401, "error": "authentication_failed"}
    assert tool.parse(json.dumps(retry), usage).failed == "The model provider refused the key (authentication_failed)"
    overloaded = tool.parse(json.dumps({**retry, "error_status": 529, "error": "overloaded"}), usage)
    assert overloaded.failed is None and overloaded.steps[0].text == "A model call failed (overloaded); retry 1"
    argv = tool.command("claude-opus-5-5")
    assert argv[:3] == ["claude", "-p", "--bare"] and argv[-2:] == ["--model", "claude-opus-5-5"]
    assert "dontAsk" in argv and "--dangerously-skip-permissions" not in argv


def test_codex_events_become_steps_and_tokens() -> None:
    tool, usage = Codex(), Usage()
    out = [tool.parse(json.dumps(e), usage) for e in (
        {"type": "thread.started", "thread_id": "t"},
        {"type": "item.started", "item": {"type": "command_execution", "command": "npm test"}},
        {"type": "item.completed", "item": {"type": "file_change", "changes": [{"path": "/sandbox/repo/a.ts"}]}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Changed a.ts; tests pass."}},
        {"type": "turn.completed", "usage": {"input_tokens": 300, "cached_input_tokens": 100, "output_tokens": 40}},
    )]
    assert [s.text for o in out for s in o.steps] == [
        "Codex started", "Ran npm test", "Edited a.ts", "Changed a.ts; tests pass."]
    assert out[3].summary == "Changed a.ts; tests pass." and usage.total == 340
    assert tool.parse(json.dumps({"type": "turn.failed", "error": {"message": "quota"}}), usage).failed == "quota"
    assert tool.command(None)[-1] == "-" and "--json" in tool.command(None)


def test_the_tool_follows_the_key_the_server_has() -> None:
    assert choose_agent(_settings()) is None
    assert choose_agent(_settings(openai_api_key=SecretStr("o"))) is CodingAgent.CODEX
    both = {"openai_api_key": SecretStr("o"), "anthropic_api_key": SecretStr("a")}
    assert choose_agent(_settings(**both)) is CodingAgent.CLAUDE_CODE
    assert choose_agent(_settings(**both, coding_agent="codex")) is CodingAgent.CODEX
    assert choose_agent(_settings(openai_api_key=SecretStr("o"), coding_agent="claude-code")) is None


def test_each_tool_says_how_it_resumes_and_reaches_its_model() -> None:
    session = uuid.uuid4()
    claude, codex = TOOLS[CodingAgent.CLAUDE_CODE], TOOLS[CodingAgent.CODEX]
    assert claude.session_args(session, resumed=False) == ["--session-id", str(session)]
    assert claude.session_args(session, resumed=True) == ["--resume", str(session)]
    assert claude.resumes and claude.browser and ".claude" in claude.save_state(session)
    assert codex.session_args(session, resumed=True) == [] and not codex.resumes and not codex.browser
    assert claude.sandbox_env("k") == {"ANTHROPIC_API_KEY": "k"}
    assert codex.sandbox_env("k") == {"OPENAI_API_KEY": "k", "CODEX_API_KEY": "k"}
    keys = _settings(anthropic_api_key=SecretStr("a"), coding_claude_model="m1", coding_codex_model="m2")
    assert claude.server_key(keys) == "a" and codex.server_key(keys) is None
    assert (claude.model(keys), codex.model(keys)) == ("m1", "m2")


def test_what_a_run_may_not_change() -> None:
    assert guard.check(["src/a.py", "docs/dotrix.md", "docs/.github/notes.md", "src/Jenkinsfile.md"]) == []
    reasons = guard.check([".dotrix/x.md", "app/.dotrix/y.md", ".github/workflows/ci.yml", "lib/.git/config"])
    assert len(reasons) == 4 and ".dotrix/ stays on the platform" in reasons[0] and "CI configuration" in reasons[2]
    ci = [".github/actions/setup/action.yml", ".github/CODEOWNERS", ".gitlab-ci.yml", ".circleci/config.yml", "Jenkinsfile",
          ".semaphore/semaphore.yml", ".cirrus.yml"]
    assert len(guard.check(ci)) == len(ci)
    assert guard.check([f"f{i}" for i in range(guard.MAX_FILES + 1)])[-1].endswith(f"more than {guard.MAX_FILES}")


def test_files_ci_runs_are_named_for_review() -> None:
    changed = ["src/a.py", "package.json", "apps/web/package.json", "tests/conftest.py", "infra/Dockerfile.worker",
               "Makefile", "README.md", ".husky/pre-commit", "apps/web/vitest.config.ts"]
    assert guard.ci_sensitive(changed) == [
        "package.json", "apps/web/package.json", "tests/conftest.py", "infra/Dockerfile.worker", "Makefile",
        ".husky/pre-commit", "apps/web/vitest.config.ts",
    ]


def test_the_policy_reaches_nothing_by_itself() -> None:
    policy = sandbox_policy()
    assert policy["network_policies"] == {} and "/" not in policy["filesystem_policy"]["read_write"]
    assert policy["landlock"]["compatibility"] == "hard_requirement"


async def test_a_process_is_streamed_and_killed_on_cancel_or_timeout() -> None:
    lines: list[str] = []

    async def on_line(line: str) -> None:
        lines.append(line.strip())

    done = await run_process([sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
                             stdin=b"brief", on_line=on_line, timeout=10)
    assert done.code == 0 and lines == ["BRIEF"]
    cancel = asyncio.Event()
    asyncio.get_running_loop().call_later(0.2, cancel.set)
    stopped = await run_process([sys.executable, "-c", "import time; time.sleep(30)"], timeout=10, cancel=cancel)
    assert stopped.cancelled and stopped.code != 0
    slow = await run_process([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.3)
    assert slow.timed_out


def test_processes_run_on_a_selector_loop_too(tmp_path) -> None:
    """The API and the worker use a selector loop on Windows (for psycopg), which can't start
    subprocesses: commands and git still run there, with threads reading the pipes."""
    from dotrix_backend.modules.code.checkouts import run_git

    async def check() -> None:
        lines: list[str] = []

        async def on_line(line: str) -> None:
            lines.append(line.strip())

        done = await run_process([sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
                                 stdin=b"brief", on_line=on_line, timeout=10)
        assert done.code == 0 and lines == ["BRIEF"]
        kept = await run_process([sys.executable, "-c", "print('kept')"], timeout=10)
        assert kept.stdout.strip() == "kept"
        cancel = asyncio.Event()
        asyncio.get_running_loop().call_later(0.2, cancel.set)
        stopped = await run_process([sys.executable, "-c", "import time; time.sleep(30)"], timeout=10, cancel=cancel)
        assert stopped.cancelled
        slow = await run_process([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.3)
        assert slow.timed_out
        await run_git(tmp_path, "init", "-q")
        assert (await run_git(tmp_path, "rev-parse", "--is-inside-work-tree")).strip() == "true"

    loop = asyncio.SelectorEventLoop()
    try:
        loop.run_until_complete(check())
    finally:
        loop.close()


def test_the_agent_gets_files_exactly_as_committed(tmp_path) -> None:
    """No line-ending conversion on the way to the sandbox, whatever this machine's git does
    (Git for Windows sets core.autocrlf=true): otherwise every line of an edited file changes."""
    from dotrix_backend.modules.code.checkouts import run_git
    from dotrix_backend.modules.coding.runner import _export

    async def check() -> None:
        repo = tmp_path / "host"
        repo.mkdir()
        await run_git(repo, "init", "-q")
        (repo / "a.py").write_bytes(b"x = 1\ny = 2\n")
        await run_git(repo, "add", "-A")
        await run_git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
        await run_git(repo, "config", "core.autocrlf", "true")  # a CRLF-minded machine, on any OS
        await _export(repo, tmp_path / "copy")
        assert (tmp_path / "copy" / "a.py").read_bytes() == b"x = 1\ny = 2\n"

    asyncio.run(check())


def test_claude_code_gets_a_browser_only_from_the_platform() -> None:
    plain = ClaudeCode().command("claude-haiku-5-5")
    assert "--strict-mcp-config" in plain and "--mcp-config" not in plain  # never a repo's MCP servers
    with_browser = ClaudeCode().command("claude-haiku-5-5", browser=True)
    config = json.loads(with_browser[with_browser.index("--mcp-config") + 1])
    assert list(config["mcpServers"]) == ["browser"] and config["mcpServers"]["browser"]["command"] == "playwright-mcp"
    assert "--headless" in config["mcpServers"]["browser"]["args"]
    assert "mcp__browser" in with_browser[with_browser.index("--allowedTools") + 1]


def test_the_browser_s_steps_read_like_the_rest() -> None:
    tool, usage = ClaudeCode(), Usage()
    started = tool.parse(json.dumps({"type": "system", "subtype": "init", "model": "claude-haiku-5-5",
                                     "mcp_servers": [{"name": "browser", "status": "failed"}]}), usage)
    assert [s.text for s in started.steps] == ["Claude Code started (claude-haiku-5-5)", "The browser didn't start (failed)"]
    calls = [
        ("mcp__browser__browser_navigate", {"url": "http://localhost:8080/"}),
        ("mcp__browser__browser_click", {"element": "Subtract button", "ref": "e4"}),
        ("mcp__browser__browser_take_screenshot", {}),
        ("mcp__browser__browser_resize", {"width": 400}),
    ]
    line = json.dumps({"type": "assistant", "message": {"id": "m1", "content": [
        {"type": "tool_use", "name": name, "input": args} for name, args in calls]}})
    assert [s.text for s in tool.parse(line, usage).steps] == [
        "Opened http://localhost:8080/ in the browser", "Clicked Subtract button", "Took a screenshot", "Used the browser (resize)"]


def _opencode_event(kind: str, **part) -> str:
    return json.dumps({"type": kind, "sessionID": "ses_x", "part": {"sessionID": "ses_x", **part}})


def test_opencode_runs_on_the_provider_its_model_names() -> None:
    tool = tool_for(CodingAgent.OPENCODE, "google_genai:gemini-3-pro")
    assert isinstance(tool, OpenCode)
    assert (tool.key_env, tool.api_host, tool.provider_type) == (
        "GOOGLE_API_KEY", "generativelanguage.googleapis.com", "dotrix-opencode-google")
    assert tool.command("google_genai:gemini-3-pro")[-2:] == ["-m", "google/gemini-3-pro"]
    assert tool_for(CodingAgent.OPENCODE, "mistral:large") is None and tool_for(CodingAgent.OPENCODE, None) is None
    assert tool_for(CodingAgent.OPENCODE, "anthropic:") is None
    assert tool_for(CodingAgent.CLAUDE_CODE, "anything") is TOOLS[CodingAgent.CLAUDE_CODE]


def test_opencode_is_chosen_only_by_name_and_with_its_provider_s_key() -> None:
    model = {"coding_opencode_model": "openai:gpt-5.5"}
    assert choose_agent(_settings(openai_api_key=SecretStr("o"), **model)) is CodingAgent.CODEX  # auto never picks it
    assert choose_agent(_settings(openai_api_key=SecretStr("o"), coding_agent="opencode", **model)) is CodingAgent.OPENCODE
    assert choose_agent(_settings(anthropic_api_key=SecretStr("a"), coding_agent="opencode", **model)) is None
    assert choose_agent(_settings(openai_api_key=SecretStr("o"), coding_agent="opencode")) is None  # no model
    assert model_for(_settings(**model), CodingAgent.OPENCODE) == "openai:gpt-5.5"


def test_opencode_s_config_is_ours_and_the_key_is_only_in_its_environment(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    tool = OpenCode(OPENCODE_PROVIDERS["anthropic"])
    argv = tool.command("anthropic:claude-haiku-5-5")
    assert argv[0] == "env" and argv[argv.index("opencode"):] == [
        "opencode", "run", "--standalone", "--format", "json", "--auto", "-m", "anthropic/claude-haiku-5-5"]
    settings = dict(pair.split("=", 1) for pair in argv[1:argv.index("opencode")])
    assert settings["OPENCODE_DISABLE_PROJECT_CONFIG"] == settings["OPENCODE_DISABLE_MODELS_FETCH"] == "1"
    config = json.loads(settings["OPENCODE_CONFIG_CONTENT"])
    assert config["enabled_providers"] == ["anthropic"] and "provider" not in config
    assert config["permission"] == {"webfetch": "deny", "websearch": "deny", "question": "deny"}
    assert tool.sandbox_env("sk-secret") == {"ANTHROPIC_API_KEY": "sk-secret"}
    assert "sk-secret" not in " ".join(argv)
    # Saving and restoring the session carry the same settings: the repo's config never loads.
    session = uuid.uuid4()
    for command in (tool.save_state(session), tool.restore_state(session), tool.usage_command(session)):
        assert "OPENCODE_DISABLE_PROJECT_CONFIG=1" in command and "--standalone" in command
    assert opencode_session(session) in tool.save_state(session)
    assert tool.session_args(session, resumed=False) == tool.session_args(session, resumed=True) == [
        "-s", f"ses_{session.hex}"]
    # A proxy in front of Anthropic: the same ANTHROPIC_BASE_URL Claude Code takes.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy:8080/")
    config = json.loads(dict(p.split("=", 1) for p in tool.command(None)[1:5])["OPENCODE_CONFIG_CONTENT"])
    assert config["provider"] == {"anthropic": {"options": {"baseURL": "http://proxy:8080/v1"}}}


def test_opencode_events_become_steps_and_tokens() -> None:
    tool, usage = OpenCode(OPENCODE_PROVIDERS["anthropic"]), Usage()
    tokens = {"input": 1000, "output": 20, "reasoning": 5, "cache": {"read": 200, "write": 0}}
    out = [tool.parse(line, usage) for line in (
        _opencode_event("step_start", messageID="m1", type="step-start"),
        _opencode_event("text", messageID="m1", type="text", text="I'll write the file."),
        _opencode_event("tool_use", messageID="m1", type="tool", tool="write",
                        state={"status": "completed", "input": {"path": "/sandbox/repo/src/a.ts", "content": "x"}}),
        _opencode_event("tool_use", messageID="m1", type="tool", tool="shell",
                        state={"status": "error", "input": {"command": "npm test"}, "error": "exit 1"}),
        _opencode_event("step_finish", messageID="m1", type="step-finish", reason="tool-calls", cost=0.01, tokens=tokens),
        _opencode_event("text", messageID="m2", type="text", text="Done."),
        "not json",
    )]
    assert [(s.kind, s.text) for o in out for s in o.steps] == [
        ("text", "I'll write the file."), ("tool", "Wrote src/a.ts"), ("error", "Ran npm test: exit 1"), ("text", "Done.")]
    assert out[5].summary == "Done." and (usage.input_tokens, usage.output_tokens) == (1200, 25)
    failed = tool.parse(json.dumps({"type": "error", "error": {"type": "provider.no-route", "message": "Model unavailable"}}), usage)
    assert failed.failed == "Model unavailable"


def test_opencode_s_totals_add_the_step_its_events_left_out() -> None:
    tool, usage = OpenCode(OPENCODE_PROVIDERS["anthropic"]), Usage()
    step = {"input": 1000, "output": 20, "reasoning": 0, "cache": {"read": 200, "write": 0}}
    tool.parse(_opencode_event("step_finish", messageID="m1", type="step-finish", tokens=step), usage)
    # The export's last turn: m1 (already counted) and m2 (the final step, never in the stream).
    tool.read_usage("noise\n" + json.dumps({"cost": 0.5, "turn": [{"id": "m1", "tokens": step}, {"id": "m2", "tokens": step}]}), usage)
    assert (usage.input_tokens, usage.output_tokens, usage.cost_usd) == (2400, 40, 0.5)
    tool.read_usage("not json", usage)  # a failed read keeps what the events said
    assert usage.total == 2440
