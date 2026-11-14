"""Optional pinned-engine tests against the desktop's real MCP server and scripted local models.

Set DOTRIX_TEST_CODEX and/or DOTRIX_TEST_FX to installed binaries. Build the desktop
package first. These tests use synthetic credentials and never contact a paid model.
"""
import json
import os
import shutil
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from dotrix_cli.fx_local import prepare_profile
from dotrix_cli.runner import BROWSER_TOKEN_ENV, Outcome, Tool, parse_line, write_browser_config
from dotrix_cli.toolenv import tool_environment

CODEX = os.environ.get("DOTRIX_TEST_CODEX")
FX = os.environ.get("DOTRIX_TEST_FX")
DESKTOP = Path(__file__).resolve().parents[3] / "apps/desktop/dist/mcp.js"


@contextmanager
def model_server(protocol, choose):
    requests, gets = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            gets.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"NETWORK_SHOULD_BE_BLOCKED")

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            index = len(requests)
            requests.append(request)
            item = choose(request, index)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if protocol == "responses":
                output = item or {"type": "message", "role": "assistant", "id": f"msg_{index}",
                                  "content": [{"type": "output_text", "text": "Done."}]}
                response = {"id": f"resp_{index}", "object": "response", "status": "completed", "output": [output],
                            "usage": {"input_tokens": 100, "output_tokens": 5, "total_tokens": 105,
                                      "input_tokens_details": {"cached_tokens": 0}}}
                events = [{"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                          {"type": "response.output_item.added", "output_index": 0, "item": output},
                          {"type": "response.output_item.done", "output_index": 0, "item": output},
                          {"type": "response.completed", "response": response}]
                self.wfile.write("".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events).encode())
            else:
                result = next((m for m in reversed(request["messages"]) if m["role"] == "tool"), None)
                delta = ({"role": "assistant", "tool_calls": [{"index": 0, "id": f"call-{index}", "type": "function",
                          "function": {"name": item[0], "arguments": json.dumps(item[1])}}]} if item else
                         {"role": "assistant", "content": str(result["content"]) if result else "Done."})
                base = {"id": "test", "object": "chat.completion.chunk", "created": 1, "model": request["model"]}
                chunks = [{**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                          {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if item else "stop"}]}]
                self.wfile.write(("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests, gets
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def desktop_browser(tmp_path):
    if not shutil.which("node") or not DESKTOP.is_file():
        pytest.skip("Build @dotrix/desktop first")
    log = tmp_path / "browser-calls.jsonl"
    script = tmp_path / "browser.cjs"
    script.write_text(f'''
const {{McpServer}}=require({json.dumps(str(DESKTOP))});
const fs=require('node:fs');
const server=new McpServer('dotrix-test','1',{{
  list:()=>[{{name:'browser_snapshot',description:'Read the browser page',inputSchema:{{type:'object',properties:{{}}}}}}],
  call:async(name,args,caller)=>{{fs.appendFileSync({json.dumps(str(log))},JSON.stringify({{name,caller}})+'\\n');
    return [{{type:'text',text:'DESKTOP_BROWSER_PROOF'}}]}}
}});
server.start().then(()=>console.log(JSON.stringify({{url:server.url,token:server.tokenFor('/runner')}})));
process.on('SIGTERM',()=>{{server.stop();process.exit(0)}});
''')
    process = subprocess.Popen(["node", str(script)], stdout=subprocess.PIPE, text=True)
    assert process.stdout
    pane = json.loads(process.stdout.readline())
    config = write_browser_config(pane["url"], pane["token"])
    try:
        yield config, pane["token"], log
    finally:
        config.unlink(missing_ok=True)
        process.terminate()
        process.wait(timeout=5)


def codex_environment(tmp_path, url):
    config = tmp_path / "codex"
    config.mkdir()
    marker = tmp_path / "untrusted-started"
    (config / "config.toml").write_text(f'''model="gpt-5.5"
model_provider="test"
sandbox_mode="danger-full-access"
[sandbox_workspace_write]
network_access=true
writable_roots=[{json.dumps(str(tmp_path))}]
[mcp_servers.untrusted]
command="touch"
args=[{json.dumps(str(marker))}]
[model_providers.test]
name="test"
base_url={json.dumps(url)}
env_key="OPENAI_API_KEY"
wire_api="responses"
''')
    return {"PATH": str(Path(CODEX).parent) + os.pathsep + os.environ["PATH"], "HOME": str(tmp_path),
            "CODEX_HOME": str(config), "OPENAI_API_KEY": "test-not-real", "LANG": "C.UTF-8"}, marker


def function(name, arguments, index, namespace=None):
    return {"type": "function_call", "id": f"fc_{index}", "call_id": f"call_{index}", "name": name,
            "arguments": json.dumps(arguments), **({"namespace": namespace} if namespace else {})}


@pytest.mark.skipif(not CODEX, reason="Set DOTRIX_TEST_CODEX to the pinned CLI")
def test_real_codex_discovers_only_the_owned_browser_and_calls_it(tmp_path, desktop_browser):
    browser, token, log = desktop_browser

    def choose(request, index):
        if index == 0:
            return {"type": "tool_search_call", "id": "search", "call_id": "search", "execution": "client",
                    "arguments": {"query": "browser_snapshot", "limit": 2}}
        if index == 1:
            namespace = next(ns for item in request["input"] if item.get("type") == "tool_search_output"
                             for ns in item["tools"] if ns.get("type") == "namespace")
            return function("browser_snapshot", {}, index, namespace["name"])

    with model_server("responses", choose) as (url, requests, _):
        env, untrusted = codex_environment(tmp_path, url)
        env[BROWSER_TOKEN_ENV] = token
        repo = tmp_path / "repo"
        repo.mkdir()
        argv = Tool.named("codex", browser=browser).argv
        assert token not in " ".join(argv)
        result = subprocess.run(argv, input="Read the browser.", text=True, capture_output=True, cwd=repo, env=env, timeout=60)
        assert result.returncode == 0, result.stderr
        assert "DESKTOP_BROWSER_PROOF" in json.dumps(requests)
        assert json.loads(log.read_text().splitlines()[0]) == {"name": "browser_snapshot", "caller": "/runner"}
        assert not untrusted.exists()
        out = Outcome()
        for line in result.stdout.splitlines():
            parse_line(line, out)
        assert any(event["text"] == "Read the page in the browser" for event in out.events)


@pytest.mark.skipif(not CODEX, reason="Set DOTRIX_TEST_CODEX to the pinned CLI")
def test_real_codex_keeps_commands_in_the_worktree_and_refuses_escalation(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with model_server("responses", lambda _, i: function("exec_command", {
        "cmd": "printf allowed > inside.txt; printf denied > ../outside.txt", "yield_time_ms": 1000,
    }, i) if i == 0 else function("exec_command", {
        "cmd": "printf denied > ../escalated.txt", "sandbox_permissions": "require_escalated",
        "justification": "Test refusal", "yield_time_ms": 1000,
    }, i) if i == 1 else None) as (url, requests, _):
        env, _ = codex_environment(tmp_path, url)
        result = subprocess.run(Tool.named("codex").argv, input="Check the boundaries.", text=True, capture_output=True,
                                cwd=repo, env=env, timeout=60)
        assert result.returncode == 0, result.stderr
        assert (repo / "inside.txt").read_text() == "allowed"
        assert not (tmp_path / "outside.txt").exists() and not (tmp_path / "escalated.txt").exists()
        assert "Read-only file system" in json.dumps(requests) or "Permission denied" in json.dumps(requests)


@pytest.mark.skipif(not FX, reason="Set DOTRIX_TEST_FX to the pinned CLI")
@pytest.mark.parametrize("operation", ["edit", "outside", "read", "outside_read", "shell", "fetch", "browser"])
def test_real_fx_local_permissions_and_desktop_browser(tmp_path, desktop_browser, operation):
    browser, _, log = desktop_browser
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "readable.txt").write_text("WORKTREE_READ_PROOF")
    (tmp_path / "private.txt").write_text("PRIVATE_READ_MUST_NOT_REACH_MODEL")

    def choose(_, index):
        if index:
            return None
        return {
            "edit": ("write_file", {"path": "inside.txt", "content": "allowed"}),
            "read": ("read_file", {"path": "readable.txt"}),
            "outside_read": ("read_file", {"path": str(tmp_path / "private.txt")}),
            "outside": ("write_file", {"path": str(tmp_path / "outside.txt"), "content": "denied"}),
            "shell": ("shell", {"request": {"action": "run", "command": f"touch {tmp_path / 'outside.txt'}"}}),
            "fetch": ("web_fetch", {"url": model_url + "/blocked"}),
            "browser": ("mcp_browser_browser_snapshot", {}),
        }[operation]

    with model_server("chat", choose) as (model_url, requests, gets):
        original = tmp_path / "original" / ".fx"
        original.mkdir(parents=True)
        saved = json.dumps({"provider": "custom", "permission_mode": "yolo", "permission": {"*": "allow"},
                            "models": {"custom": "test"}, "providers": {"custom": {
                                "protocol": "openai-chat-completions", "base_url": model_url,
                                "auth": {"type": "bearer", "env": "LOCAL_TEST_KEY"},
                                "model_metadata": {"test": {"supports_tool_use": True}},
                            }}})
        (original / "settings.json").write_text(saved)
        env = tool_environment("fx", {"HOME": str(original.parent), "PATH": str(Path(FX).parent) + os.pathsep + os.environ["PATH"],
                                      "LOCAL_TEST_KEY": "test-not-real", "GITHUB_TOKEN": "unrelated-host-key"})
        profile = tmp_path / "isolated"
        prepare_profile(profile, env)
        result = subprocess.run(Tool.named("fx", browser=browser, profile=profile).argv, input="Check this task.",
                                text=True, capture_output=True, cwd=repo, env=env, timeout=60)
        assert result.returncode == 0, result.stderr
        assert (original / "settings.json").read_text() == saved
        assert not (tmp_path / "outside.txt").exists() and not gets
        if operation == "edit":
            assert (repo / "inside.txt").read_text() == "allowed"
        elif operation == "browser":
            assert "DESKTOP_BROWSER_PROOF" in result.stdout
            assert json.loads(log.read_text().splitlines()[0])["caller"] == "/runner"
        elif operation == "read":
            assert "WORKTREE_READ_PROOF" in json.dumps(requests)
        else:
            assert '"status": "failed"' in result.stdout or "denied" in result.stdout.lower() or "not found" in result.stdout.lower()
        assert len(requests) >= 2
        assert "PRIVATE_READ_MUST_NOT_REACH_MODEL" not in json.dumps(requests)
