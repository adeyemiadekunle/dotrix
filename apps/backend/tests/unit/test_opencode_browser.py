"""Optional real OpenCode + Playwright check, with a local scripted model (no model keys).

Set DOTRIX_TEST_OPENCODE, DOTRIX_TEST_PLAYWRIGHT_MCP and DOTRIX_TEST_CHROMIUM to
the pinned binaries, or put them on PATH. The coding image's network isolation is
covered separately; this test proves the engine can actually drive its MCP browser.
"""
import copy
import json
import os
import shlex
import shutil
import subprocess
import threading
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from dotrix_backend.modules.coding import tools

OPENCODE = os.environ.get("DOTRIX_TEST_OPENCODE") or shutil.which("opencode")
MCP = os.environ.get("DOTRIX_TEST_PLAYWRIGHT_MCP") or shutil.which("playwright-mcp")
CHROMIUM = os.environ.get("DOTRIX_TEST_CHROMIUM") or shutil.which("chromium")
ROOT = Path(__file__).resolve().parents[4]


@contextmanager
def _serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.skipif(not (OPENCODE and MCP and CHROMIUM), reason="Needs pinned OpenCode, Playwright MCP and Chromium")
def test_opencode_drives_browser_on_new_and_resumed_turns(tmp_path, monkeypatch):
    marker = f"clicked-proof-{uuid.uuid4().hex}"
    hits = []

    class App(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write((f'<title>Browser check</title><button onclick="document.querySelector(\'h1\').textContent='
                              f"'{marker}'\">Verify</button><h1>Not clicked</h1>").encode())

    with _serve(App) as app_url:
        code = r'''await tools.browser.browser_navigate({url: URL});
const page = await tools.browser.browser_snapshot({});
const text = typeof page === 'string' ? page : JSON.stringify(page);
const match = text.match(/button "Verify" \[ref=([^\]]+)\]/);
if (!match) throw new Error('Verify button missing from snapshot');
await tools.browser.browser_click({target: match[1], element: 'Verify'});
const snapshot = await tools.browser.browser_snapshot({});
await tools.browser.browser_take_screenshot({filename: 'proof.png', type: 'png', scale: 'css'});
return snapshot;'''.replace("URL", json.dumps(app_url))
        requests = []

        class Model(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append(request)
                messages = request["messages"]
                last_user = max(i for i, message in enumerate(messages) if message["role"] == "user")
                result = next((m for m in reversed(messages[last_user + 1:]) if m["role"] == "tool"), None)
                can_execute = any(t.get("function", {}).get("name") == "execute" for t in request.get("tools", []))
                if result is None and can_execute:
                    delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": f"call-{len(requests)}", "type": "function",
                             "function": {"name": "execute", "arguments": json.dumps({"code": code})}}]}
                    finish = "tool_calls"
                else:
                    delta = {"role": "assistant", "content": f"Result: {result['content']}" if result else "Browser check"}
                    finish = "stop"
                base = {"id": "test", "object": "chat.completion.chunk", "created": 1, "model": request["model"]}
                chunks = [{**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                          {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode())

        output, repo = tmp_path / "browser", tmp_path / "repo"
        repo.mkdir()
        untrusted = tmp_path / "untrusted-server-started"
        (repo / "opencode.json").write_text(json.dumps({"mcp": {"untrusted": {"type": "local", "command": ["touch", str(untrusted)]}}}))
        servers = copy.deepcopy(tools.BROWSER_MCP)
        server = servers["mcpServers"]["browser"]
        server["args"][1] = (server["args"][1].replace(tools.BROWSER_OUTPUT, shlex.quote(str(output)))
                             + " --executable-path " + shlex.quote(CHROMIUM))
        monkeypatch.setattr(tools, "BROWSER_MCP", servers)
        monkeypatch.setattr(tools, "MCP_CHECK", str(ROOT / "infra/coding/mcp-check.mjs"))
        env = {"PATH": os.pathsep.join([str(Path(OPENCODE).parent), str(Path(MCP).parent), os.environ["PATH"]]),
               "NVIDIA_API_KEY": "test-not-real",
               **{f"XDG_{key}_HOME": str(tmp_path / key.lower()) for key in ("DATA", "CONFIG", "CACHE", "STATE")}}
        version = subprocess.run([OPENCODE, "--version"], env=env, capture_output=True, text=True, check=True, timeout=15)
        assert version.stdout.strip() == "opencode v2.3.0", "Use the coding image's pinned version"
        tool = tools.OpenCode(tools.OPENCODE_PROVIDERS["nvidia"])
        session = uuid.uuid4()
        with _serve(Model) as model_url:
            for resumed in (False, True):
                argv = tool.command("nvidia:browser-test", browser=True) + tool.session_args(session, resumed)
                # Test transport only: production still uses the fixed provider endpoint.
                for index, arg in enumerate(argv):
                    if arg.startswith("OPENCODE_CONFIG_CONTENT="):
                        config = json.loads(arg.partition("=")[2])
                        config["provider"]["nvidia"]["options"]["baseURL"] = model_url + "/v1"
                        argv[index] = "OPENCODE_CONFIG_CONTENT=" + json.dumps(config)
                completed = subprocess.run(argv, input="Verify the browser.", env=env, cwd=repo, capture_output=True,
                                           text=True, timeout=90)
                assert completed.returncode == 0, completed.stderr
                parsed = [tool.parse(line, tools.Usage()) for line in completed.stdout.splitlines()]
                assert marker in " ".join(result.summary or "" for result in parsed), completed.stdout
                steps = [step.text for result in parsed for step in result.steps]
                assert f"Opened {app_url} in the browser" in steps and "Clicked Verify" in steps and "Took a screenshot" in steps
                screenshot = output / "proof.png"
                assert screenshot.read_bytes().startswith(b"\x89PNG")
                screenshot.unlink()  # the resumed turn must create a fresh screenshot
                assert not list(repo.rglob("*.png")) and not list(repo.rglob("*.yml"))
        assert len(hits) >= 2 and not untrusted.exists()


def test_failed_browser_startup_keeps_the_brief_and_continues_the_turn(tmp_path, monkeypatch):
    if not shutil.which("node") or os.name == "nt":
        pytest.skip("Needs Node and a POSIX shell")
    monkeypatch.setattr(tools, "MCP_CHECK", str(ROOT / "infra/coding/mcp-check.mjs"))
    monkeypatch.setattr(tools, "BROWSER_MCP", {"mcpServers": {"browser": {"command": "/missing-browser-binary", "args": []}}})
    binary = tmp_path / "opencode"
    binary.write_text("#!/bin/sh\nprintf '%s\\n' '{\"type\":\"text\",\"part\":{\"text\":\"Continued without a browser\"}}'\ncat\n")
    binary.chmod(0o700)
    tool = tools.OpenCode(tools.OPENCODE_PROVIDERS["nvidia"])
    completed = subprocess.run(tool.command("nvidia:browser-test", browser=True), input="BRIEF_SURVIVED", text=True,
                               capture_output=True, env={"PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]}, timeout=20)
    assert completed.returncode == 0 and completed.stdout.endswith("BRIEF_SURVIVED")
    parsed = [tool.parse(line, tools.Usage()) for line in completed.stdout.splitlines()]
    assert any(result.summary == "Continued without a browser" for result in parsed)
    assert any(step.text == "The browser didn't start" for result in parsed for step in result.steps)
