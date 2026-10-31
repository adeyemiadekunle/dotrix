"""fx as Kai's engine: when it's offered and chosen, the driver's command and saved state, its JSON lines read
into steps and tokens, and the driver itself (infra/coding/fx-acp.mjs) against a fake `fx acp`."""
import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

import pytest

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.coding.models import CodingAgent
from dotrix_backend.modules.coding.tools import (
    FX_PROVIDERS,
    OPENCODE_PROVIDERS,
    TOOLS,
    Fx,
    OpenCode,
    Usage,
    choose_agent,
    fx_models,
    model_for,
    models_for,
    tool_for,
)

DRIVER = Path(__file__).resolve().parents[4] / "infra" / "coding" / "fx-acp.mjs"


def _settings(**values) -> Settings:
    base = {"database_url": "postgresql+asyncpg://localhost/unused", "jwt_secret": "x" * 40,
            "anthropic_api_key": None, "openai_api_key": None}
    return Settings(**{**base, **values})  # type: ignore[arg-type]


def test_fx_is_offered_but_never_the_automatic_choice() -> None:
    on = _settings(coding_fx_model="openai:gpt-6.1")
    assert "openai:gpt-6.1" in fx_models(on, {"openai"})
    assert choose_agent(on, {"openai"}) is CodingAgent.CODEX  # nobody asked for it
    assert choose_agent(on, {"openai"}, preferred="fx") is CodingAgent.FX
    assert choose_agent(_settings(coding_agent="fx", coding_fx_model="openai:gpt-6.1"), {"openai"}) is CodingAgent.FX


def test_fx_runs_on_openai_compatible_providers_only() -> None:
    on = _settings(coding_fx_model="openai:gpt-6.1")
    assert model_for(on, CodingAgent.FX, {"openai"}) == "openai:gpt-6.1"
    assert "openai:gpt-6.1" in models_for(on, CodingAgent.FX, {"openai"})
    assert all(m.partition(":")[0] in FX_PROVIDERS for m in fx_models(on, {"openai", "anthropic", "xai"}))
    assert "google_genai" not in FX_PROVIDERS  # not yet: no OpenAI-compatible endpoint checked
    assert isinstance(tool_for(CodingAgent.FX, "xai:grok-4.7", on), Fx)
    anthropic = tool_for(CodingAgent.FX, "anthropic:claude-haiku-5-5", on)  # Anthropic's OpenAI-compatible endpoint
    assert isinstance(anthropic, Fx) and "https://api.anthropic.com/v1" in anthropic.command("anthropic:claude-haiku-5-5")
    assert tool_for(CodingAgent.FX, "google_genai:gemini-3.8-flash", on) is None
    assert tool_for(CodingAgent.FX, "openai", on) is None  # no model


def test_fx_command_reaches_one_provider_with_its_key_by_name(monkeypatch) -> None:
    settings = _settings(coding_fx_driver="/opt/dotrix/fx-acp.mjs")
    tool = tool_for(CodingAgent.FX, "xai:grok-4.7", settings)
    assert tool is not None
    assert tool.command("xai:grok-4.7") == [
        "node", "/opt/dotrix/fx-acp.mjs", "--base-url", "https://api.x.ai/v1", "--key-env", "XAI_API_KEY",
        "--model", "grok-4.7",
    ]
    assert tool.sandbox_env("secret") == {"XAI_API_KEY": "secret"}
    assert (tool.api_host, tool.provider_type) == ("api.x.ai", "dotrix-fx-xai")
    monkeypatch.setenv("XAI_BASE_URL", "https://proxy.example/xai/")  # never followed
    assert "https://api.x.ai/v1" in tool.command("xai:grok-4.7")


def test_fx_continues_its_session_from_saved_state() -> None:
    tool = Fx(FX_PROVIDERS["openai"])
    session = uuid.UUID(int=7)
    assert tool.session_args(session, resumed=False) == ["--session", session.hex]
    assert tool.session_args(session, resumed=True) == ["--session", session.hex, "--resume"]
    assert ".fx" in tool.save_state(session) and "--exclude=.fx/settings.json" in tool.save_state(session)


def _lines(*events: dict) -> list[str]:
    return [json.dumps(event) for event in events]


def test_fx_lines_become_steps_terminal_output_and_tokens() -> None:
    tool, usage = Fx(FX_PROVIDERS["openai"]), Usage()
    steps, summary, failed = [], None, None
    for line in _lines(
        {"type": "started", "model": "gpt-6.1", "resumed": False},
        {"type": "text", "text": "Looking at the tests."},
        {"type": "tool", "id": "c1", "name": "shell", "title": "Run", "input": {"request": {"action": "run", "command": "pytest -q"}}},
        {"type": "tool_result", "id": "c1", "status": "completed", "output": "3 passed\n"},
        {"type": "tool", "id": "c2", "name": "edit_file", "input": {"path": "/sandbox/repo/app.py"}},
        {"type": "tool", "id": "c3", "name": "write_file", "input": {"path": "notes.md"}},
        {"type": "tool_result", "id": "c3", "status": "failed", "output": "denied"},
        {"type": "done", "stopReason": "end_turn", "final": "Fixed it.",
         "usage": {"inputTokens": 100, "cacheReadTokens": 20, "outputTokens": 30, "reasoningTokens": 5}},
    ) + ["not json", ""]:
        parsed = tool.parse(line, usage)
        steps += parsed.steps
        summary = parsed.summary or summary
        failed = parsed.failed or failed
    said = [(s.kind, s.text, s.ref) for s in steps]
    assert said == [
        ("step", "Started (gpt-6.1)", None),
        ("text", "Looking at the tests.", None),
        ("tool", "Ran pytest -q", "c1"),
        ("output", "3 passed", "c1"),
        ("tool", "Edited app.py", None),
        ("tool", "Wrote notes.md", None),
        ("error", "Wrote notes.md: denied", None),
    ]
    assert (summary, failed) == ("Fixed it.", None)
    assert (usage.input_tokens, usage.output_tokens) == (120, 35)


def test_fx_turns_that_end_early_say_why() -> None:
    tool = Fx(FX_PROVIDERS["openai"])
    assert tool.parse(json.dumps({"type": "done", "stopReason": "cancelled"}), Usage()).failed == "Stopped"
    assert tool.parse(json.dumps({"type": "done", "stopReason": "weird"}), Usage()).failed == "Kai stopped (weird)"
    assert tool.parse(json.dumps({"type": "error", "message": "x"}), Usage()).failed == "x"


# -- the driver, against a fake `fx acp` --------------------------------------------------------------------

FAKE_FX = textwrap.dedent('''
    import json, os, sys
    log = open(os.environ["FAKE_FX_LOG"], "a")
    def send(message):
        sys.stdout.write(json.dumps(message) + "\\n"); sys.stdout.flush()
    def update(session, body):
        send({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": session, "update": body}})
    waiting = None
    for line in sys.stdin:
        msg = json.loads(line)
        log.write(json.dumps({"method": msg.get("method"), "params": msg.get("params")}) + "\\n"); log.flush()
        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": 1}})
        elif method == "session/new":
            send({"jsonrpc": "2.0", "id": mid, "result": {"sessionId": "fx-session-1"}})
        elif method == "session/resume":
            update(msg["params"]["sessionId"], {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "old"}})
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif method == "session/set_mode":
            send({"jsonrpc": "2.0", "id": mid, "result": None})
        elif method == "session/prompt":
            sid = msg["params"]["sessionId"]
            if "provider" in msg["params"]["prompt"][0]["text"]:  # call the model the way fx does: the settings' base_url
                import urllib.error, urllib.request
                url = json.load(open(os.path.join(os.environ["HOME"], ".fx", "settings.json")))["providers"]["dotrix"]["base_url"]
                log.write(json.dumps({"method": "provider", "params": {"base_url": url}}) + "\\n"); log.flush()
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # fx itself never uses a proxy
                try:
                    opener.open(urllib.request.Request(url + "/chat/completions", data=b"{}", method="POST"), timeout=10)
                    reason = "end_turn"
                except urllib.error.HTTPError as error:
                    reason = "refused" if error.code == 403 else "error"
                send({"jsonrpc": "2.0", "id": mid, "result": {"stopReason": reason}})
                continue
            if "wait" in msg["params"]["prompt"][0]["text"]:
                waiting = mid
                update(sid, {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Working"}})
                continue
            update(sid, {"sessionUpdate": "agent_message_chunk", "messageId": "m1", "content": {"type": "text", "text": "Looking"}})
            update(sid, {"sessionUpdate": "agent_message_chunk", "messageId": "m1", "content": {"type": "text", "text": " now."}})
            update(sid, {"sessionUpdate": "tool_call", "toolCallId": "c1", "name": "shell", "title": "Run", "kind": "execute",
                         "status": "pending", "rawInput": {"request": {"action": "run", "command": "pytest -q"}}})
            update(sid, {"sessionUpdate": "tool_call_update", "toolCallId": "c1", "status": "completed",
                         "content": [{"type": "content", "content": {"type": "text", "text": "3 passed\\n"}}]})
            update(sid, {"sessionUpdate": "usage_update", "used": 8, "size": 128000})
            update(sid, {"sessionUpdate": "agent_message_chunk", "messageId": "m2", "content": {"type": "text", "text": "Done."}})
            send({"jsonrpc": "2.0", "id": mid, "result": {"stopReason": "end_turn", "usage": {"inputTokens": 10, "outputTokens": 4}}})
        elif method == "session/cancel" and waiting is not None:
            send({"jsonrpc": "2.0", "id": waiting, "result": {"stopReason": "cancelled"}})
            waiting = None
''')


@pytest.fixture
def fake_fx(tmp_path: Path) -> dict[str, str]:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "fx"
    script.write_text(f"#!{sys.executable}\n{FAKE_FX}")
    script.chmod(0o755)
    home = tmp_path / "home"
    (home / "repo").mkdir(parents=True)
    proxies = {"HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"}  # a test sets its own
    return {**{k: v for k, v in os.environ.items() if k not in proxies}, "HOME": str(home), "DOTRIX_FX_BIN": str(script),
            "FAKE_FX_LOG": str(tmp_path / "fx.log"), "OPENAI_API_KEY": "the-key"}


def _drive(env: dict[str, str], brief: str, *extra: str) -> list[dict]:
    argv = ["node", str(DRIVER), "--base-url", "https://api.openai.com/v1", "--key-env", "OPENAI_API_KEY",
            "--model", "gpt-6.1", "--session", "s1", *extra]
    done = subprocess.run(argv, input=brief, capture_output=True, text=True, env=env, timeout=30,
                          cwd=Path(env["HOME"]) / "repo")
    return [json.loads(line) for line in done.stdout.splitlines() if line.strip()]


def _calls(env: dict[str, str]) -> list[dict]:
    return [json.loads(line) for line in Path(env["FAKE_FX_LOG"]).read_text().splitlines()]


def test_the_driver_runs_a_turn_in_full_access_with_our_provider_settings(fake_fx) -> None:
    events = _drive(fake_fx, "Fix the tests")
    assert [e["type"] for e in events] == ["started", "text", "tool", "tool_result", "text", "done"]
    assert events[1]["text"] == "Looking now." and events[4]["text"] == "Done."
    assert events[2] == {"type": "tool", "id": "c1", "name": "shell", "title": "Run", "kind": "execute",
                         "input": {"request": {"action": "run", "command": "pytest -q"}}}
    assert events[3] == {"type": "tool_result", "id": "c1", "status": "completed", "output": "3 passed\n"}
    assert events[5] == {"type": "done", "stopReason": "end_turn", "usage": {"inputTokens": 10, "outputTokens": 4},
                         "final": "Done."}
    calls = _calls(fake_fx)
    assert [c["method"] for c in calls] == ["initialize", "session/new", "session/set_mode", "session/prompt"]
    assert calls[2]["params"] == {"sessionId": "fx-session-1", "modeId": "full-access"}
    assert calls[3]["params"]["prompt"] == [{"type": "text", "text": "Fix the tests"}]
    home = Path(fake_fx["HOME"])
    settings = json.loads((home / ".fx" / "settings.json").read_text())
    assert settings["providers"]["dotrix"]["auth"] == {"type": "bearer", "env": "OPENAI_API_KEY"}  # its name, not the key
    assert "the-key" not in (home / ".fx" / "settings.json").read_text()
    assert settings["models"] == {"dotrix": "gpt-6.1"} and settings["auto_upgrade"] is False
    assert json.loads((home / ".fx" / "dotrix" / "s1.json").read_text()) == {"fxSession": "fx-session-1"}

    # The parsed lines, as Codes shows them.
    tool, usage = Fx(FX_PROVIDERS["openai"]), Usage()
    steps = [s for e in events for s in tool.parse(json.dumps(e), usage).steps]
    assert ("tool", "Ran pytest -q") in [(s.kind, s.text) for s in steps]
    assert (usage.input_tokens, usage.output_tokens) == (10, 4)


def test_the_next_turn_continues_fx_s_session_without_replaying_it(fake_fx) -> None:
    _drive(fake_fx, "First")
    events = _drive(fake_fx, "Second", "--resume")
    assert events[0] == {"type": "started", "model": "gpt-6.1", "resumed": True}
    assert "old" not in [e.get("text") for e in events]  # the resumed history isn't this turn's
    methods = [c["method"] for c in _calls(fake_fx)]
    assert methods[4:] == ["initialize", "session/resume", "session/set_mode", "session/prompt"]


def test_sigint_cancels_the_turn_and_it_still_ends_with_done(fake_fx) -> None:
    argv = ["node", str(DRIVER), "--base-url", "https://api.openai.com/v1", "--key-env", "OPENAI_API_KEY",
            "--model", "gpt-6.1"]
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=fake_fx,
                               cwd=Path(fake_fx["HOME"]) / "repo")
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write("Please wait")
    process.stdin.close()
    assert json.loads(process.stdout.readline())["type"] == "started"
    deadline = time.monotonic() + 10
    while "session/prompt" not in Path(fake_fx["FAKE_FX_LOG"]).read_text() and time.monotonic() < deadline:
        time.sleep(0.05)
    process.send_signal(signal.SIGINT)
    rest = [json.loads(line) for line in process.stdout.read().splitlines() if line.strip()]
    assert process.wait(timeout=10) == 0
    assert rest[-1]["type"] == "done" and rest[-1]["stopReason"] == "cancelled"
    assert "session/cancel" in [c["method"] for c in _calls(fake_fx)]


ENGINES = ("claude", "codex", "opencode", "fx")


@pytest.mark.parametrize("tool", [
    TOOLS[CodingAgent.CLAUDE_CODE], TOOLS[CodingAgent.CODEX], OpenCode(OPENCODE_PROVIDERS["openai"]), Fx(FX_PROVIDERS["openai"]),
], ids=lambda tool: tool.name)
def test_what_people_read_never_names_the_engine(tool) -> None:
    """Steps and failures reach Codes; the engine is only on the run, in the audit log, and in logs."""
    starts = [  # each engine's first event, and a failure without its own message
        {"type": "system", "subtype": "init", "model": "m"}, {"type": "result", "subtype": "error_during_execution"},
        {"type": "thread.started"}, {"type": "turn.failed", "error": {}}, {"type": "error", "error": {}},
        {"type": "started", "model": "m"}, {"type": "done", "stopReason": "max_turn_requests"}, {"type": "error"},
    ]
    said = []
    for event in starts:
        parsed = tool.parse(json.dumps(event), Usage())
        said += [s.text for s in parsed.steps] + ([parsed.failed] if parsed.failed else [])
    assert said, "no event was read"
    assert not [text for text in said if any(name in text.lower() for name in ENGINES)]


def test_the_driver_s_own_failures_never_name_fx(fake_fx) -> None:
    env = {**fake_fx, "DOTRIX_FX_BIN": "/nonexistent/fx"}
    events = _drive(env, "Fix it")
    assert events[-1]["type"] == "error" and "fx" not in events[-1]["message"].lower()


def test_behind_an_egress_proxy_fx_calls_a_local_forwarder_and_a_refusal_is_the_sandboxs(fake_fx) -> None:
    """fx ignores HTTPS_PROXY, so the driver points it at a forwarder on 127.0.0.1 that tunnels through the proxy;
    a proxy that refuses the provider ends the turn at once, said as the sandbox's refusal, not the model's."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    asked: list[str] = []

    class Refusing(BaseHTTPRequestHandler):
        def do_CONNECT(self) -> None:  # noqa: N802 (the HTTP method's name)
            asked.append(self.path)
            self.send_response(403)
            self.end_headers()

        def log_message(self, *args) -> None:
            pass

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Refusing)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        events = _drive({**fake_fx, "HTTPS_PROXY": f"http://127.0.0.1:{proxy.server_address[1]}"}, "Ask the provider")
    finally:
        proxy.shutdown()
    url = next(c["params"]["base_url"] for c in _calls(fake_fx) if c["method"] == "provider")
    assert url.startswith("http://127.0.0.1:") and url.endswith("/v1")  # the forwarder, keeping the provider's path
    assert asked == ["api.openai.com:443"]  # the forwarder tunnels to the configured provider only
    assert events[-1] == {"type": "error", "message": "The sandbox doesn't allow this model provider (its egress proxy refused it)"}
