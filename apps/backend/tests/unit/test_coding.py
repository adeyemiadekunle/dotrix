"""Coding runs' pure parts: reading Claude Code's and Codex's JSON events, choosing the tool by
the key the server has, what a run's changes may not touch, and stopping a process."""
import asyncio
import json
import sys
import uuid

import pytest
from pydantic import SecretStr, ValidationError

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.coding import guard
from dotrix_backend.modules.coding.models import CodingAgent
from dotrix_backend.modules.coding.sandbox import run_process, sandbox_policy
from dotrix_backend.modules.coding.schemas import RunnerHeartbeat, RunnerResult
from dotrix_backend.modules.coding.tools import (
    CLAUDE_ENV,
    OPENCODE_PROVIDERS,
    TOOLS,
    ClaudeCode,
    Codex,
    OpenCode,
    Usage,
    choose_agent,
    model_for,
    opencode_session,
    run_key,
    tool_for,
)


def _settings(**values) -> Settings:
    base = {"database_url": "postgresql+asyncpg://localhost/unused", "jwt_secret": "x" * 40,
            "anthropic_api_key": None, "openai_api_key": None}
    return Settings(**{**base, **values})  # type: ignore[arg-type]


@pytest.mark.parametrize("agent", list(CodingAgent))
def test_hosted_research_keeps_the_selected_browser_and_is_opt_in(agent: CodingAgent) -> None:
    engine = tool_for(agent, "openai:test")
    assert engine is not None
    session = "a" * 32
    assert "research-mcp.mjs" not in " ".join(engine.command("openai:test", browser=True))
    argv = " ".join(engine.command("openai:test", browser=True, browser_engine="agent-browser", research=(session, True)))
    assert "agent-browser-mcp.mjs" in argv and "research-mcp.mjs" in argv and session in argv


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
        ("step", "Started (claude-opus-5-5)"), ("text", "Looking."), ("tool", "Ran pytest -q"),
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
    assert argv[:4] == ["env", *CLAUDE_ENV] and argv[-2:] == ["--model", "claude-opus-5-5"]
    assert argv[4:8] == ["claude", "-p", "--setting-sources", ""] and "--bare" not in argv
    assert "dontAsk" in argv and "--dangerously-skip-permissions" not in argv


def test_claude_codes_refused_tool_calls_are_shown_once() -> None:
    """`dontAsk` refuses what isn't allowed; the session says so instead of the call vanishing. The
    events are as Claude Code 2.1.296 prints them: a `permission_denied` event when it refuses, then
    the call again in its result's `permission_denials` (only that one carries the input)."""
    tool, usage = ClaudeCode(), Usage()
    lines = [
        {"type": "assistant", "message": {"id": "m1", "content": [
            {"type": "tool_use", "id": "toolu_2", "name": "Bash", "input": {"command": "touch /tmp/x"}},
            {"type": "tool_use", "id": "toolu_3", "name": "TaskCreate", "input": {"subject": "Touch"}}]}},
        {"type": "system", "subtype": "permission_denied", "tool_name": "Bash", "tool_use_id": "toolu_2",
         "decision_reason_type": "mode", "message": "Permission to use Bash has been denied"},
        # Its result is the engine's refusal, naming the engine: not shown as the command's output.
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_2",
         "is_error": True, "content": "Permission to use Bash has been denied because Claude Code is running in …"}]}},
        {"type": "system", "subtype": "permission_denied", "tool_name": "NotebookEdit", "tool_use_id": "toolu_4"},
        {"type": "result", "subtype": "success", "result": "Done.", "total_cost_usd": 0.01, "permission_denials": [
            {"tool_name": "Bash", "tool_use_id": "toolu_2", "tool_input": {"command": "touch /tmp/x"}},
            {"tool_name": "Write", "tool_use_id": "toolu_5", "tool_input": {"file_path": "/sandbox/repo/.env"}}]},
    ]
    steps = [(s.kind, s.text) for line in lines for s in tool.parse(json.dumps(line), usage).steps]
    assert steps == [
        ("tool", "Ran touch /tmp/x"),  # its own checklist (TaskCreate) is no step
        ("error", "Not allowed to run touch /tmp/x"),
        ("error", "Not allowed to use NotebookEdit"),
        ("error", "Not allowed to change .env"),  # only in the result: said there
    ]


def test_codex_events_become_steps_and_tokens() -> None:
    tool, usage = Codex(), Usage()
    out = [tool.parse(json.dumps(e), usage) for e in (
        {"type": "thread.started", "thread_id": "t"},
        {"type": "item.started", "item": {"id": "c1", "type": "command_execution", "command": "npm test"}},
        {"type": "item.completed", "item": {"id": "c1", "type": "command_execution", "command": "npm test",
                                            "aggregated_output": "2 passed\n", "exit_code": 0}},
        {"type": "item.completed", "item": {"type": "file_change", "changes": [{"path": "/sandbox/repo/a.ts"}]}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Changed a.ts; tests pass."}},
        {"type": "turn.completed", "usage": {"input_tokens": 300, "cached_input_tokens": 100, "output_tokens": 40}},
    )]
    assert [s.text for o in out for s in o.steps] == [
        "Started", "Ran npm test", "2 passed", "Edited a.ts", "Changed a.ts; tests pass."]
    assert out[1].steps[0].ref == out[2].steps[0].ref == "c1" and out[2].steps[0].kind == "output"
    assert out[4].summary == "Changed a.ts; tests pass." and usage.total == 340
    assert tool.parse(json.dumps({"type": "turn.failed", "error": {"message": "quota"}}), usage).failed == "quota"
    assert tool.command(None)[-1] == "-" and "--json" in tool.command(None)


def test_tools_follow_only_the_persons_own_keys() -> None:
    legacy = _settings(openai_api_key=SecretStr("server"), anthropic_api_key=SecretStr("server"), server_model_keys=True)
    assert choose_agent(legacy) is None
    assert choose_agent(legacy, {"openai"}) is CodingAgent.FX
    assert choose_agent(legacy, {"anthropic"}) is CodingAgent.FX
    assert choose_agent(legacy, {"openai", "anthropic"}) is CodingAgent.FX
    assert choose_agent(legacy, {"openai"}, preferred="claude-code") is CodingAgent.FX
    assert choose_agent(legacy, {"openai"}, preferred="codex") is CodingAgent.CODEX


def test_a_persons_default_needs_a_compatible_key_and_auto_supports_other_providers() -> None:
    both = _settings(openai_api_key=SecretStr("o"), anthropic_api_key=SecretStr("a"))
    assert choose_agent(both, {"anthropic", "openai"}, preferred="claude-code") is CodingAgent.CLAUDE_CODE
    assert choose_agent(both, {"anthropic", "openai"}, preferred="opencode") is CodingAgent.OPENCODE
    assert choose_agent(_settings(), {"xai"}) is CodingAgent.FX
    assert model_for(_settings(), CodingAgent.OPENCODE, {"xai"}) == "xai:grok-4.7"
    assert choose_agent(_settings(), {"xai"}, preferred="codex") is CodingAgent.FX
    assert choose_agent(_settings(), {"google_genai"}) is CodingAgent.OPENCODE
    assert choose_agent(_settings(openai_api_key=SecretStr("  "))) is None
    for provider in ("xai", "deepseek", "mistral", "groq", "openrouter", "nvidia"):
        spec = OPENCODE_PROVIDERS[provider]
        model = f"{provider}:test-model"
        tool = tool_for(CodingAgent.OPENCODE, model)
        assert tool is not None
        assert tool.sandbox_env("only-this-key") == {spec.key_env: "only-this-key"}
        assert tool.api_host == spec.api_host
        config = json.loads(dict(pair.split("=", 1) for pair in tool.command(model)[1:5])["OPENCODE_CONFIG_CONTENT"])
        assert config["enabled_providers"] == [spec.opencode]


def test_each_tool_says_how_it_resumes_and_reaches_its_model() -> None:
    session = uuid.uuid4()
    claude, codex = TOOLS[CodingAgent.CLAUDE_CODE], TOOLS[CodingAgent.CODEX]
    assert claude.session_args(session, resumed=False) == ["--session-id", str(session)]
    assert claude.session_args(session, resumed=True) == ["--resume", str(session)]
    assert claude.resumes and claude.browser and ".claude" in claude.save_state(session)
    assert codex.session_args(session, resumed=True) == [] and not codex.resumes and codex.browser
    assert claude.sandbox_env("k") == {"ANTHROPIC_API_KEY": "k"}
    assert codex.sandbox_env("k") == {"OPENAI_API_KEY": "k", "CODEX_API_KEY": "k"}
    keys = _settings(anthropic_api_key=SecretStr("a"), coding_claude_model="m1", coding_codex_model="m2")
    assert run_key(claude, keys, {}) is None and run_key(codex, keys, {}) is None
    assert (claude.model(keys), codex.model(keys)) == ("m1", "m2")


def test_what_a_run_may_not_change() -> None:
    key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"
    import base64 as b64
    assert guard.leaks(key, b"+API_KEY = '" + key.encode() + b"'\n")
    assert guard.leaks(key, None, f"set it to {b64.b64encode(key.encode()).decode().rstrip('=')}")
    assert guard.leaks(key, b64.urlsafe_b64encode(key.encode()))
    assert not guard.leaks(key, b"+API_KEY = os.environ['ANTHROPIC_API_KEY']\n", "Reads the key from the environment.")
    assert not guard.leaks(None, key) and not guard.leaks("short", "short")  # no key, or too short to tell
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


def test_a_sessions_hosts_become_passthrough_endpoints_for_any_program() -> None:
    policy = sandbox_policy(["registry.npmjs.org", "*.example.com", "registry.example.com:8443"])
    [rule] = policy["network_policies"].values()
    assert rule["endpoints"] == [
        {"host": "registry.npmjs.org", "port": 443, "tls": "skip"},
        {"host": "**.example.com", "port": 443, "tls": "skip"},  # *.domain is every host under it, as in the policy
        {"host": "registry.example.com", "port": 8443, "tls": "skip"},
    ]
    assert rule["binaries"] == [{"path": "/**"}]


async def test_openshell_opens_its_sandbox_with_the_sessions_hosts(tmp_path, monkeypatch) -> None:
    import json
    import uuid

    from dotrix_backend.core.settings import Settings
    from dotrix_backend.modules.coding.sandbox import OpenShellSandbox
    from dotrix_backend.modules.coding.tools import ClaudeCode

    calls, policies = [], []

    async def cli(self, *args, env=None):
        calls.append(list(args))
        if args[:2] == ("sandbox", "create"):
            policies.append(json.loads(open(args[args.index("--policy") + 1]).read()))
        return ""

    monkeypatch.setattr(OpenShellSandbox, "cli", cli)
    (tmp_path / "a.txt").write_text("x")
    sandbox = OpenShellSandbox(Settings(database_url="postgresql+asyncpg://localhost/unused",
                                        jwt_secret="test-only-secret-long-enough-for-settings"))
    session = await sandbox.open(uuid.uuid4(), tmp_path, ClaudeCode(), "sk-test", allow=["pypi.org"])
    assert policies[0]["network_policies"]["project_hosts"]["endpoints"] == [{"host": "pypi.org", "port": 443, "tls": "skip"}]
    assert "sk-test" not in " ".join(" ".join(c) for c in calls)  # the key goes to the provider by environment
    await session.close()
    assert ["sandbox", "delete", session.name] in calls


def test_a_secret_host_is_inspected_by_its_provider_not_relayed() -> None:
    from dotrix_backend.modules.coding.sandbox import secret_profile
    from dotrix_backend.modules.coding.secrets import HostSecret

    policy = sandbox_policy(["registry.npmjs.org", "pypi.org"], ["registry.npmjs.org"])
    assert policy["network_policies"]["project_hosts"]["endpoints"] == [{"host": "pypi.org", "port": 443, "tls": "skip"}]
    assert sandbox_policy(["registry.npmjs.org"], ["registry.npmjs.org"])["network_policies"] == {}
    npm = secret_profile("ps-x-1", HostSecret("NPM_TOKEN", "registry.npmjs.org", 443, "Authorization", "Bearer ", "v", 1))
    assert npm["credentials"] == [{"name": "value", "description": "Host secret NPM_TOKEN", "env_vars": ["NPM_TOKEN"],
                                   "required": True, "auth_style": "bearer"}]
    assert npm["endpoints"] == [{"host": "registry.npmjs.org", "port": 443, "protocol": "rest", "access": "read-write",
                                 "enforcement": "enforce"}]
    api = secret_profile("ps-x-2", HostSecret("TEST_API", "api.example.com", 8443, "X-Api-Key", "", "v", 1))
    assert api["credentials"][0]["auth_style"] == "header" and api["credentials"][0]["header_name"] == "X-Api-Key"
    assert api["endpoints"][0]["port"] == 8443


async def test_openshell_attaches_a_provider_per_secret_and_removes_them(tmp_path, monkeypatch) -> None:
    import uuid

    from dotrix_backend.core.settings import Settings
    from dotrix_backend.modules.coding.sandbox import OpenShellSandbox
    from dotrix_backend.modules.coding.secrets import HostSecret
    from dotrix_backend.modules.coding.tools import ClaudeCode

    calls, envs, profiles = [], [], []

    async def cli(self, *args, env=None):
        calls.append(list(args))
        envs.append(env or {})
        if args[:3] == ("provider", "profile", "import"):
            profiles.append(open(args[args.index("-f") + 1]).read())
        return ""

    monkeypatch.setattr(OpenShellSandbox, "cli", cli)
    (tmp_path / "a.txt").write_text("x")
    sandbox = OpenShellSandbox(Settings(database_url="postgresql+asyncpg://localhost/unused",
                                        jwt_secret="test-only-secret-long-enough-for-settings"))
    run_id = uuid.uuid4()
    secret = HostSecret("NPM_TOKEN", "registry.npmjs.org", 443, "Authorization", "Bearer ", "npm-real-value", 1)
    session = await sandbox.open(run_id, tmp_path, ClaudeCode(), "sk-test", allow=["registry.npmjs.org"],
                                 secrets=[secret])
    provider = f"ps-{run_id.hex[-13:]}-1"
    assert len(provider) <= 19
    assert ["provider", "create", "--name", provider, "--type", provider, "--credential", "NPM_TOKEN"] in calls
    assert any(e.get("NPM_TOKEN") == "npm-real-value" for e in envs)  # by environment only
    assert "npm-real-value" not in " ".join(" ".join(c) for c in calls) and "npm-real-value" not in "".join(profiles)
    create = next(c for c in calls if c[:2] == ["sandbox", "create"])
    assert create[create.index("--provider") + 1] != provider and provider in create
    await session.close()
    assert ["provider", "delete", provider] in calls and ["provider", "profile", "delete", provider] in calls


async def test_openshell_detaches_a_setup_only_secret(tmp_path, monkeypatch) -> None:
    import uuid

    from dotrix_backend.core.settings import Settings
    from dotrix_backend.modules.coding.sandbox import OpenShellSandbox
    from dotrix_backend.modules.coding.secrets import HostSecret
    from dotrix_backend.modules.coding.tools import ClaudeCode

    calls = []

    async def cli(self, *args, env=None):
        calls.append(list(args))
        return ""

    monkeypatch.setattr(OpenShellSandbox, "cli", cli)
    (tmp_path / "a.txt").write_text("x")
    sandbox = OpenShellSandbox(Settings(database_url="postgresql+asyncpg://localhost/unused",
                                        jwt_secret="test-only-secret-long-enough-for-settings"))
    run_id = uuid.uuid4()
    session = await sandbox.open(run_id, tmp_path, ClaudeCode(), "sk-test", allow=["pypi.org"], secrets=[
        HostSecret("PYPI_TOKEN", "pypi.org", 443, "Authorization", "Bearer ", "v", 1, "setup")])
    provider = f"ps-{run_id.hex[-13:]}-1"
    await session.drop_secrets(["PYPI_TOKEN"])
    assert ["sandbox", "provider", "detach", session.name, provider] in calls
    assert session.secret_providers == [] and session.profiles == []
    calls.clear()
    await session.close()  # what was already removed isn't removed again
    assert ["provider", "delete", provider] not in calls


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
    server = config["mcpServers"]["browser"]
    assert list(config["mcpServers"]) == ["browser"] and server["command"] == "sh" and server["args"][0] == "-c"
    # Started in its output folder, which is its only workspace root: a screenshot it names never lands in the repository.
    script = server["args"][1]
    assert script.startswith("mkdir -p /tmp/playwright && cd /tmp/playwright && ")
    assert 'export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/ms-playwright}" && exec playwright-mcp ' in script
    assert "--headless" in script and "--ignore-roots" in script and "--output-dir /tmp/playwright" in script
    assert "mcp__browser" in with_browser[with_browser.index("--allowedTools") + 1]


def test_codex_gets_the_browser_and_says_when_it_didnt_start() -> None:
    """Checked on Codex 0.169.0 with the real Playwright MCP 0.0.85 against a scripted Responses API: it calls the
    browser without asking, and goes on silently when it doesn't start, so mcp-check.mjs runs first."""
    from dotrix_backend.modules.coding.tools import BROWSER_MCP, MCP_CHECK, Codex, Usage

    tool = Codex()
    assert tool.browser
    plain = tool.command("openai:gpt-5.5")
    assert plain[0] == "codex" and plain[-1] == "-" and not any("mcp_servers" in arg for arg in plain)
    argv = tool.command("openai:gpt-5.5", browser=True)
    assert argv[:4] == ["sh", "-c", 'node "$1" --mcp-config "$2"; shift 2; exec "$@"', "sh"]
    assert argv[4] == MCP_CHECK and json.loads(argv[5]) == BROWSER_MCP
    codex = argv[6:]
    assert codex[0] == "codex" and codex[-1] == "-"  # the brief still on stdin
    server = BROWSER_MCP["mcpServers"]["browser"]
    assert f"mcp_servers.browser.command={json.dumps(server['command'])}" in codex
    assert f"mcp_servers.browser.args={json.dumps(server['args'])}" in codex
    assert "project_doc_max_bytes=0" in codex  # the repository's AGENTS.md is still never its instructions

    usage = Usage()
    lines = [
        {"type": "warning", "message": "The browser didn't start"},
        {"type": "item.started", "item": {"id": "i1", "type": "mcp_tool_call", "server": "browser", "tool": "browser_navigate",
                                          "arguments": {"url": "http://localhost:8080/"}, "status": "in_progress"}},
        {"type": "item.completed", "item": {"id": "i1", "type": "mcp_tool_call", "server": "browser", "tool": "browser_navigate",
                                            "arguments": {"url": "http://localhost:8080/"}, "status": "completed", "error": None}},
        {"type": "item.completed", "item": {"id": "i2", "type": "mcp_tool_call", "server": "browser", "tool": "browser_click",
                                            "arguments": {}, "status": "failed", "error": {"message": "No such element"}}},
    ]
    steps = [(s.kind, s.text) for line in lines for s in tool.parse(json.dumps(line), usage).steps]
    assert steps == [("error", "The browser didn't start"), ("tool", "Opened http://localhost:8080/ in the browser"),
                     ("error", "The browser: No such element")]


def test_the_browser_s_steps_read_like_the_rest() -> None:
    tool, usage = ClaudeCode(), Usage()
    started = tool.parse(json.dumps({"type": "system", "subtype": "init", "model": "claude-haiku-5-5",
                                     "mcp_servers": [{"name": "browser", "status": "failed"}]}), usage)
    assert [s.text for s in started.steps] == ["Started (claude-haiku-5-5)", "The browser didn't start (failed)"]
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
    assert tool_for(CodingAgent.OPENCODE, "unsupported:large") is None and tool_for(CodingAgent.OPENCODE, None) is None
    assert tool_for(CodingAgent.OPENCODE, "anthropic:") is None
    assert tool_for(CodingAgent.CLAUDE_CODE, "anything") is TOOLS[CodingAgent.CLAUDE_CODE]


def test_opencode_uses_an_available_personal_provider_without_server_keys() -> None:
    model = {"coding_opencode_model": "openai:gpt-5.5"}
    assert choose_agent(_settings(**model), {"openai"}) is CodingAgent.FX
    assert choose_agent(_settings(coding_agent="opencode", **model), {"openai"}) is CodingAgent.OPENCODE
    assert choose_agent(_settings(coding_agent="opencode", **model), {"anthropic"}) is CodingAgent.OPENCODE
    assert choose_agent(_settings(coding_agent="opencode"), {"openai"}) is CodingAgent.OPENCODE
    assert choose_agent(_settings(coding_agent="opencode")) is None
    assert model_for(_settings(**model), CodingAgent.OPENCODE, {"openai"}) == "openai:gpt-5.5"


def test_opencode_s_config_is_ours_and_the_key_is_only_in_its_environment(monkeypatch) -> None:
    tool = OpenCode(OPENCODE_PROVIDERS["anthropic"])
    argv = tool.command("anthropic:claude-haiku-5-5")
    assert argv[0] == "env" and argv[argv.index("opencode"):] == [
        "opencode", "run", "--standalone", "--format", "json", "--auto", "-m", "anthropic/claude-haiku-5-5"]
    settings = dict(pair.split("=", 1) for pair in argv[1:argv.index("opencode")])
    assert settings["OPENCODE_DISABLE_PROJECT_CONFIG"] == settings["OPENCODE_DISABLE_MODELS_FETCH"] == "1"
    config = json.loads(settings["OPENCODE_CONFIG_CONTENT"])
    assert config["enabled_providers"] == ["anthropic"]
    assert config["provider"] == {"anthropic": {"models": {"claude-haiku-5-5": {}}}}
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
    # Nothing in the worker's environment sends the key elsewhere.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy:8080/")
    config = json.loads(dict(p.split("=", 1) for p in tool.command(None)[1:5])["OPENCODE_CONFIG_CONTENT"])
    assert "provider" not in config


def test_opencode_gets_only_the_platform_browser_and_reports_startup_failure() -> None:
    from dotrix_backend.modules.coding.tools import BROWSER_MCP, MCP_CHECK

    tool = OpenCode(OPENCODE_PROVIDERS["nvidia"])
    assert tool.browser
    argv = tool.command("nvidia:nvidia/nemotron-3-ultra-550b-a55b", browser=True)
    assert argv[:2] == ["sh", "-c"] and argv[4] == MCP_CHECK
    assert json.loads(argv[5]) == BROWSER_MCP
    command = argv[6:]
    env = dict(pair.split("=", 1) for pair in command[1:command.index("opencode")])
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    server = BROWSER_MCP["mcpServers"]["browser"]
    assert config["mcp"] == {"browser": {"type": "local", "command": [server["command"], *server["args"]]}}
    assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert config["permission"]["webfetch"] == "deny"
    assert "/tmp/playwright" in str(config["mcp"]) and "--ignore-roots" in str(config["mcp"])
    plain = tool.command("nvidia:nvidia/nemotron-3-ultra-550b-a55b")
    assert "mcp" not in json.loads(next(arg.split("=", 1)[1] for arg in plain if arg.startswith("OPENCODE_CONFIG_CONTENT=")))
    warning = tool.parse(json.dumps({"type": "warning", "message": "The browser didn't start"}), Usage())
    assert warning.failed is None and [(s.kind, s.text) for s in warning.steps] == [("error", "The browser didn't start")]


def test_opencode_browser_steps_cover_code_mode_and_direct_tool_calls() -> None:
    tool, usage = OpenCode(OPENCODE_PROVIDERS["openai"]), Usage()
    events = [
        ("execute", {"code": "return await tools.browser.browser_snapshot({})"}, "Used the browser"),
        ("execute", {"code": "return 1 + 1"}, "Ran a script"),
        ("browser_browser_navigate", {"url": "http://localhost:8080/"}, "Opened http://localhost:8080/ in the browser"),
        ("browser_browser_take_screenshot", {}, "Took a screenshot"),
    ]
    for name, args, expected in events:
        result = tool.parse(_opencode_event("tool_use", tool=name, state={"status": "completed", "input": args}), usage)
        assert [step.text for step in result.steps] == [expected]


def test_opencode_reports_actual_nested_browser_calls_and_script_errors() -> None:
    tool = OpenCode(OPENCODE_PROVIDERS["nvidia"])
    calls = [{"tool": "browser.browser_navigate", "status": "completed", "input": {"url": "http://localhost:8080"}},
             {"tool": "browser.browser_click", "status": "completed", "input": {"element": "Verify", "target": "e2"}},
             {"tool": "browser.browser_take_screenshot", "status": "completed", "input": {"filename": "proof.png"}}]
    state = {"status": "completed", "input": {"code": "return await verify()"},
             "metadata": {"metadata": {"toolCalls": calls}}}
    steps = tool.parse(_opencode_event("tool_use", tool="execute", state=state), Usage()).steps
    assert [step.text for step in steps] == ["Opened http://localhost:8080 in the browser", "Clicked Verify", "Took a screenshot"]
    calls[1]["status"] = "error"
    state["output"] = "No such element"
    steps = tool.parse(_opencode_event("tool_use", tool="execute", state=state), Usage()).steps
    assert steps[1].kind == "error" and steps[1].text == "The browser: No such element"
    state["metadata"]["metadata"] = {"error": True, "toolCalls": []}
    state["output"] = "Unknown browser tool"
    result = tool.parse(_opencode_event("tool_use", tool="execute", state=state), Usage())
    assert result.failed is None and result.steps[0].kind == "error" and "Unknown browser tool" in result.steps[0].text
    calls[1]["status"] = "completed"
    state.update(status="error", error="Bridge stopped", metadata={"metadata": {"toolCalls": calls}})
    result = tool.parse(_opencode_event("tool_use", tool="execute", state=state), Usage())
    assert result.steps[-1].kind == "error" and result.steps[-1].text == "The browser script: Bridge stopped"


def test_opencode_events_become_steps_and_tokens() -> None:
    tool, usage = OpenCode(OPENCODE_PROVIDERS["anthropic"]), Usage()
    tokens = {"input": 1000, "output": 20, "reasoning": 5, "cache": {"read": 200, "write": 0}}
    out = [tool.parse(line, usage) for line in (
        _opencode_event("step_start", messageID="m1", type="step-start"),
        _opencode_event("text", messageID="m1", type="text", text="I'll write the file."),
        _opencode_event("tool_use", messageID="m1", type="tool", tool="write",
                        state={"status": "completed", "input": {"path": "/sandbox/repo/src/a.ts", "content": "x"}}),
        _opencode_event("tool_use", messageID="m1", type="tool", tool="shell", callID="t-shell",
                        state={"status": "error", "input": {"command": "npm test"}, "error": "exit 1"}),
        _opencode_event("step_finish", messageID="m1", type="step-finish", reason="tool-calls", cost=0.01, tokens=tokens),
        _opencode_event("text", messageID="m2", type="text", text="Done."),
        "not json",
    )]
    assert [(s.kind, s.text) for o in out for s in o.steps] == [
        ("text", "I'll write the file."), ("tool", "Wrote src/a.ts"), ("tool", "Ran npm test"), ("output-error", "exit 1"),
        ("text", "Done.")]
    ran, output = out[3].steps
    assert ran.ref == output.ref == "t-shell"  # paired for the Terminal
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


def test_a_run_uses_only_a_supplied_personal_key() -> None:
    claude = TOOLS[CodingAgent.CLAUDE_CODE]
    server = _settings(anthropic_api_key=SecretStr("server"))
    assert run_key(claude, server, {"anthropic": "theirs"}) == "theirs"
    assert run_key(claude, server, {"openai": "other"}) is None
    hosted = server.model_copy(update={"server_model_keys": False})  # everyone brings their own
    assert run_key(claude, hosted, {}) is None
    # A tool can code where there's a key for its provider: the workspace's or the person's, or the server's.
    assert choose_agent(_settings()) is None
    assert choose_agent(_settings(), {"anthropic"}) is CodingAgent.FX
    assert choose_agent(_settings(), {"openai"}) is CodingAgent.FX
    assert choose_agent(hosted) is None and choose_agent(hosted, {"anthropic"}) is CodingAgent.FX
    opencode = _settings(coding_agent="opencode", coding_opencode_model="google_genai:gemini-3-pro")
    assert choose_agent(opencode, {"anthropic"}) is CodingAgent.OPENCODE
    assert choose_agent(opencode, {"google_genai"}) is CodingAgent.OPENCODE
    assert tool_for(CodingAgent.OPENCODE, "google_genai:gemini-3-pro").provider == "google_genai"


def test_a_session_codes_on_its_model_and_the_engine_follows_it() -> None:
    from dotrix_backend.modules.coding.tools import engine_for, kai_models

    settings = _settings(coding_fx_model="openai:gpt-6.1")
    keys = {"anthropic", "openai", "xai", "google_genai"}
    models = kai_models(settings, keys)
    claude = next(m for m in models if m.startswith("anthropic:"))
    gpt = next(m for m in models if m.startswith("openai:"))
    grok = next(m for m in models if m.startswith("xai:"))
    gemini = next(m for m in models if m.startswith("google_genai:"))
    # Nothing preferred: the Kai runtime's fx where it supports the model, else OpenCode.
    assert engine_for(settings, claude, keys) is CodingAgent.FX
    assert engine_for(settings, gpt, keys) is CodingAgent.FX
    assert engine_for(settings, grok, keys) is CodingAgent.FX
    assert engine_for(settings, gemini, keys) is CodingAgent.OPENCODE
    # A preferred engine (Account → Your models) wins where it can run the model.
    assert engine_for(settings, gpt, keys, "opencode") is CodingAgent.OPENCODE
    assert engine_for(settings, gpt, keys, "codex") is CodingAgent.CODEX
    assert engine_for(settings, grok, keys, "fx") is CodingAgent.FX
    assert engine_for(settings, claude, keys, "fx") is CodingAgent.FX  # through Anthropic's OpenAI-compatible endpoint
    assert engine_for(settings, claude, keys, "claude-code") is CodingAgent.CLAUDE_CODE
    assert engine_for(settings, claude, keys, "codex") is CodingAgent.FX
    assert "anthropic:x" not in kai_models(settings, {"openai"})


def test_claude_code_and_codex_take_the_model_as_their_engine_names_it() -> None:
    assert ClaudeCode().command("anthropic:claude-haiku-5-5")[-2:] == ["--model", "claude-haiku-5-5"]
    assert ClaudeCode().command("claude-haiku-5-5")[-2:] == ["--model", "claude-haiku-5-5"]  # a server setting's bare name
    assert Codex().command("openai:gpt-5.5")[-3:] == ["-c", 'model="gpt-5.5"', "-"]
    # The repository's AGENTS.md never reaches Codex's model as instructions.
    codex = Codex().command(None)
    assert codex[codex.index("project_doc_max_bytes=0") - 1] == "-c"


@pytest.mark.parametrize("value", ["-" + "a" * 39, "A" * 40, "g" * 40, "a" * 39, "a" * 41, "--upload-pack=" + "x" * 26])
def test_a_runner_base_commit_must_be_a_full_hex_id(value):
    with pytest.raises(ValidationError):
        RunnerHeartbeat(lease_token=1, base_sha=value)
    with pytest.raises(ValidationError):
        RunnerResult(lease_token=1, outcome="no_changes", base_sha=value)


def test_a_runner_base_commit_accepts_a_real_id_or_none():
    for value in ("0123456789abcdef0123456789abcdef01234567", None):
        assert RunnerHeartbeat(lease_token=1, base_sha=value).base_sha == value
        assert RunnerResult(lease_token=1, outcome="no_changes", base_sha=value).base_sha == value


def test_agent_browser_mcp_selector_and_step_descriptions() -> None:
    from dotrix_backend.modules.coding.tools import (
        AGENT_BROWSER_MCP,
        BROWSER_MCP,
        Fx,
        _describe_browser,
        browser_mcp,
        tool_for,
    )

    assert browser_mcp() == BROWSER_MCP
    assert browser_mcp("agent-browser") == AGENT_BROWSER_MCP
    fx = tool_for(CodingAgent.FX, "openai:gpt-5.5", _settings())
    assert isinstance(fx, Fx)
    argv = fx.command("openai:gpt-5.5", browser=True, browser_engine="agent-browser")
    assert json.loads(argv[argv.index("--mcp-config") + 1]) == AGENT_BROWSER_MCP
    claude_argv = ClaudeCode().command("claude-haiku-5-5", browser=True, browser_engine="agent-browser")
    assert json.loads(claude_argv[claude_argv.index("--mcp-config") + 1]) == AGENT_BROWSER_MCP

    assert _describe_browser("browser_open", {"url": "http://localhost:3000"}) == "Opened http://localhost:3000 in the browser"
    assert _describe_browser("browser_snapshot", {}) == "Read the page"
    assert _describe_browser("browser_click", {"ref": "@e2"}) == "Clicked @e2"
    assert _describe_browser("browser_fill", {"ref": "@e3", "text": "ada"}) == "Filled in @e3"
    assert _describe_browser("browser_screenshot", {"filename": "proof.png"}) == "Took a screenshot"
    assert _describe_browser("browser_close", {}) == "Closed the browser"


def test_coding_agent_legacy_rolls_back_defaults_while_allowing_explicit_fx() -> None:
    from dotrix_backend.modules.coding.tools import engine_for, kai_models

    settings = _settings(coding_agent="legacy", coding_fx_model="openai:gpt-6.1")
    keys = {"anthropic", "openai", "xai"}
    models = kai_models(settings, keys)
    claude = next(m for m in models if m.startswith("anthropic:"))
    gpt = next(m for m in models if m.startswith("openai:"))
    grok = next(m for m in models if m.startswith("xai:"))

    assert engine_for(settings, claude, keys) is CodingAgent.CLAUDE_CODE
    assert engine_for(settings, gpt, keys) is CodingAgent.CODEX
    assert engine_for(settings, grok, keys) is CodingAgent.OPENCODE
    assert choose_agent(settings, {"openai"}) is CodingAgent.CODEX
    assert choose_agent(settings, {"anthropic"}) is CodingAgent.CLAUDE_CODE
    assert choose_agent(settings, {"xai"}) is CodingAgent.OPENCODE
    assert engine_for(settings, claude, keys, "fx") is CodingAgent.FX
    assert choose_agent(settings, {"openai"}, preferred="fx") is CodingAgent.FX


def _flag(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


def test_claude_code_starts_kai_s_workers_and_lists_them_with_its_background_tasks() -> None:
    """Its subagents (`Agent`): Kai's workers by name (`--agents`) and its own general-purpose one, each within
    `--tools`. The events are as Claude Code 2.1.323 printed them against a scripted model."""
    tool, usage = ClaudeCode(), Usage()
    argv = tool.command(None)
    assert "Agent" in _flag(argv, "--tools").split(",") and "Agent" in _flag(argv, "--allowedTools").split(",")
    agents = json.loads(_flag(argv, "--agents"))
    assert set(agents) == {"explorer", "tester", "reviewer"}
    assert agents["explorer"]["tools"] == ["Read", "Glob", "Grep"]
    assert agents["tester"]["tools"] == ["Bash", "Read", "Glob", "Grep"]
    assert agents["explorer"]["maxTurns"] == 30 and agents["explorer"]["prompt"].startswith("You are one of Kai's workers.")
    lines = [
        {"type": "system", "subtype": "init", "model": "claude-haiku-5-5", "tools": ["Agent", "Read"]},
        {"type": "assistant", "parent_tool_use_id": None, "message": {"id": "msg_1", "content": [
            {"type": "tool_use", "id": "toolu_0001", "name": "Agent",
             "input": {"subagent_type": "explorer", "description": "find the answer", "prompt": "What is the answer?"}}],
            "usage": {"input_tokens": 10, "output_tokens": 1}}},
        {"type": "system", "subtype": "task_started", "task_id": "ae4ac377f695a5bd0", "tool_use_id": "toolu_0001",
         "description": "find the answer", "subagent_type": "explorer", "is_backgrounded": True, "task_type": "local_agent"},
        # The helper's own messages: what it does is named for it, and its words are its report's, not Kai's.
        {"type": "assistant", "parent_tool_use_id": "toolu_0001", "message": {"id": "msg_2", "content": [
            {"type": "tool_use", "id": "toolu_0002", "name": "Read", "input": {"file_path": "/sandbox/repo/a.py"}},
            {"type": "text", "text": "HELPER-REPORT: the answer is 42"}], "usage": {"input_tokens": 10, "output_tokens": 1}}},
        {"type": "system", "subtype": "task_notification", "task_id": "ae4ac377f695a5bd0", "tool_use_id": "toolu_0001",
         "status": "completed", "summary": "HELPER-REPORT: the answer is 42"},
        {"type": "system", "subtype": "task_notification", "task_id": "ae4ac377f695a5bd0", "status": "completed"},
        {"type": "system", "subtype": "task_started", "task_id": "b1", "task_type": "local_bash", "description": "npm test"},
        # Its report comes back as another turn of the same run: not a new start.
        {"type": "system", "subtype": "init", "model": "claude-haiku-5-5"},
        {"type": "assistant", "parent_tool_use_id": None, "message": {"id": "msg_3", "content": [
            {"type": "text", "text": "The answer is 42."}], "usage": {"input_tokens": 10, "output_tokens": 1}}},
    ]
    steps = [(s.kind, s.text, s.ref) for line in lines for s in tool.parse(json.dumps(line), usage).steps]
    assert steps == [
        ("step", "Started (claude-haiku-5-5)", None),
        ("tool", "Asked explorer to find the answer", None),
        ("background-running", "explorer: find the answer", "worker:ae4ac377f695a5bd0"),
        ("tool", "Read a.py (explorer)", None),
        ("background-done", "explorer: find the answer", "worker:ae4ac377f695a5bd0"),
        ("text", "The answer is 42.", None),
    ]
    assert usage.input_tokens == 30  # the helper's model calls count too


def test_codex_s_helpers_are_capped_and_listed_with_its_background_tasks() -> None:
    """Codex's subagents (`multi_agent`): at most two at once, none starting its own; `collab_tool_call` items as
    Codex 0.169.0 printed them against a scripted model."""
    tool, usage = Codex(), Usage()
    argv = tool.command("openai:gpt-5.5")
    assert "agents.max_threads=3" in argv and "agents.max_depth=1" in argv
    parent, child = "01a21eaf-8f1d-7f83-a3de-4185e5f2b9d5", "01a21eaf-9024-75e2-b26b-8cb8b5688f6d"
    lines = [
        {"type": "item.started", "item": {"id": "item_1", "type": "collab_tool_call", "tool": "spawn_agent",
         "sender_thread_id": parent, "receiver_thread_ids": [], "prompt": "What is the answer?", "agents_states": {},
         "status": "in_progress"}},
        {"type": "item.completed", "item": {"id": "item_1", "type": "collab_tool_call", "tool": "spawn_agent",
         "sender_thread_id": parent, "receiver_thread_ids": [child], "prompt": "What is the answer?",
         "agents_states": {child: {"status": "pending_init", "message": None}}, "status": "completed"}},
        {"type": "item.completed", "item": {"id": "item_2", "type": "collab_tool_call", "tool": "wait",
         "sender_thread_id": parent, "receiver_thread_ids": [child], "prompt": None,
         "agents_states": {child: {"status": "completed", "message": "HELPER-REPORT: the answer is 42"}},
         "status": "completed"}},
        {"type": "item.completed", "item": {"id": "item_3", "type": "collab_tool_call", "tool": "close_agent",
         "sender_thread_id": parent, "receiver_thread_ids": [child], "agents_states": {child: {"status": "shutdown"}}}},
    ]
    steps = [(s.kind, s.text, s.ref) for line in lines for s in tool.parse(json.dumps(line), usage).steps]
    assert steps == [
        ("tool", "Asked a helper to What is the answer?", None),
        ("background-running", "a helper: What is the answer?", f"worker:{child}"),
        ("background-done", "a helper: What is the answer?", f"worker:{child}"),  # closing it after isn't news
    ]


def test_opencode_starts_kai_s_workers_under_their_own_permissions() -> None:
    """OpenCode runs a subagent under its own permissions, not its caller's (2.3.0): each of Kai's workers may use
    only its own tools. Its report comes back to the turn unseen by the stream, so how it ended is read from the
    session's export after the turn."""
    tool, usage = OpenCode(OPENCODE_PROVIDERS["nvidia"]), Usage()
    argv = tool.command("nvidia:test")
    config = json.loads(next(a.partition("=")[2] for a in argv if a.startswith("OPENCODE_CONFIG_CONTENT=")))
    agents = config["agents"]
    assert set(agents) == {"explorer", "tester", "reviewer"} and agents["explorer"]["mode"] == "subagent"
    rules = agents["explorer"]["permissions"]
    assert rules[0] == {"action": "*", "resource": "*", "effect": "deny"}
    allowed = [r["action"] for r in rules if r["effect"] == "allow"]
    assert allowed == ["read", "glob", "grep"]
    assert [r["action"] for r in agents["tester"]["permissions"] if r["effect"] == "allow"] == ["shell", "read", "glob", "grep"]
    assert {"subagent", "skill", "webfetch", "websearch", "question"} <= {r["action"] for r in rules[1 + len(allowed):]}
    child = "ses_de154d512ffexbbL1tNSzobxl6"
    event = {"type": "tool_use", "sessionID": "ses_parent", "part": {"type": "tool", "id": "call-2", "tool": "subagent",
             "state": {"status": "completed", "input": {"agent": "explorer", "description": "find the answer",
                                                        "prompt": "What is the answer?"},
                       "metadata": {"metadata": {"sessionID": child, "status": "running"}},
                       "output": "The subagent is working in the background"}}}
    steps = [(s.kind, s.text, s.ref) for s in tool.parse(json.dumps(event), usage).steps]
    assert steps == [("tool", "Asked explorer to find the answer", None),
                     ("background-running", "explorer: find the answer", f"worker:{child}")]
    tool.read_usage(json.dumps({"cost": 0, "turn": [], "helpers": [[child, "completed"], ["ses_other", "error"]]}), usage)
    assert [(s.kind, s.ref) for s in usage.late] == [("background-done", f"worker:{child}")]


def test_opencode_s_totals_read_how_its_helpers_ended_from_the_session_export(tmp_path) -> None:
    """`_OPENCODE_TOTALS` on an export shaped as OpenCode 2.3.0 wrote one: a helper's report is a `synthetic`
    message; an earlier turn's are left out."""
    import shutil
    import subprocess

    from dotrix_backend.modules.coding.tools import _OPENCODE_TOTALS

    if not shutil.which("node"):
        pytest.skip("Needs Node")
    export = {"info": {"cost": 0.01}, "messages": [
        {"type": "user", "text": "earlier"},
        {"type": "synthetic", "text": '<subagent sessionID="ses_old" state="completed" description="x">\nold\n</subagent>'},
        {"type": "user", "text": "Use your helper\n"},
        {"type": "assistant", "id": "msg_1", "tokens": {"input": 10, "output": 5}},
        {"type": "synthetic", "text": '<subagent sessionID="ses_new" state="completed" description="find">\nHELPER\n</subagent>'},
        {"type": "assistant", "id": "msg_2", "tokens": {"input": 10, "output": 5}},
        {"type": "idle", "outcome": "succeeded"},
    ]}
    out = subprocess.run(["node", "-e", _OPENCODE_TOTALS], input=json.dumps(export), capture_output=True, text=True,
                         timeout=30, check=True)
    totals = json.loads(out.stdout)
    assert totals["helpers"] == [["ses_new", "completed"]] and [s["id"] for s in totals["turn"]] == ["msg_1", "msg_2"]


def test_a_runner_may_report_kai_s_helpers_as_background_tasks() -> None:
    """A local turn's helpers are listed as a cloud turn's (`background-<state>`, `ref` `worker:<id>`), and a claim says
    the platform takes them: a runner that doesn't see it (an older platform) reports them as steps."""
    from dotrix_backend.modules.coding.schemas import CodingClaim

    beat = RunnerHeartbeat.model_validate({"lease_token": 1, "events": [
        {"kind": "background-running", "text": "explorer: find the answer", "ref": "worker:ae4ac377"},
        {"kind": "background-done", "text": "explorer: find the answer", "ref": "worker:ae4ac377"}]})
    assert [e.kind for e in beat.events] == ["background-running", "background-done"]
    with pytest.raises(ValidationError):
        RunnerHeartbeat.model_validate({"lease_token": 1, "events": [{"kind": "background-anything", "text": "x"}]})
    assert CodingClaim.model_fields["helper_events"].default is True
