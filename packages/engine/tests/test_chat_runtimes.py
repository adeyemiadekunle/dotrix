"""The runtime validates host configuration and model policy."""
import asyncio
import json
import os
from types import SimpleNamespace

import pytest

from dotrix_engine.runtimes import (
    AgentRuntimeConfig,
    DeepAgentsRuntime,
    ModelPolicy,
    ModelSelection,
    RuntimeTool,
    UnsupportedRuntimeOperation,
    fx_configuration_digest,
)
from dotrix_engine.runtimes.fx import _prepare_local_dir
from dotrix_engine.testing import ScriptedChatModel


def test_duplicate_tools_are_rejected():
    async def read(arguments):
        return arguments

    tool = RuntimeTool("read", "Read a document", {"type": "object"}, read)
    with pytest.raises(ValueError):
        AgentRuntimeConfig("orion", "You are Orion", (tool, tool))


async def test_deepagents_capabilities_and_cancellation():
    runtime = DeepAgentsRuntime(AgentRuntimeConfig("orion", "You are Orion"), ScriptedChatModel.of("Answer"))
    session = await runtime.new_session()
    assert runtime.capabilities.streaming and runtime.capabilities.cancellation
    assert not runtime.capabilities.steering and not runtime.capabilities.resume
    with pytest.raises(UnsupportedRuntimeOperation):
        await runtime.resume(session)
    with pytest.raises(UnsupportedRuntimeOperation):
        await runtime.steer(session, "Change direction")
    started = asyncio.Event()

    class SlowGraph:
        async def aget_state(self, config):
            return SimpleNamespace(values={})

        async def astream(self, *args, **kwargs):
            started.set()
            await asyncio.Event().wait()
            yield None

    runtime.graph = SlowGraph()
    turn = asyncio.create_task(runtime.prompt(session, "Question"))
    await started.wait()
    await runtime.cancel(session)
    with pytest.raises(asyncio.CancelledError):
        await turn
    await runtime.close()


def test_model_policy_selects_host_tier_and_rejects_unknown_tiers():
    policy = ModelPolicy(
        tiers={"strong": ModelSelection("strong-model", "high"), "economy": ModelSelection("cheap-model")},
        agents={"project-manager": "strong"}, default="economy",
    )
    assert policy.resolve("project-manager") == ModelSelection("strong-model", "high")
    assert policy.resolve("research").model == "cheap-model"
    assert policy.resolve("research", task_tier="strong").model == "strong-model"
    with pytest.raises(ValueError):
        policy.resolve("research", task_tier="unconfigured")


def test_local_store_is_bound_to_its_agent_and_configuration(tmp_path):
    path = tmp_path / "session-store"
    config = AgentRuntimeConfig("orion", "Private project instructions")
    _prepare_local_dir(path, config, "model-a", None, None, 128_000)
    _prepare_local_dir(path, config, "model-a", None, None, 128_000)
    assert "Private project instructions" not in (path / ".dotrix-fx-runtime.json").read_text()
    assert json.loads((path / ".dotrix-fx-runtime.json").read_text())["digest"] == fx_configuration_digest(
        config, model="model-a")
    with pytest.raises(ValueError, match="different runtime configuration"):
        _prepare_local_dir(path, config, "model-b", None, None, 128_000)
    with pytest.raises(ValueError, match="different runtime configuration"):
        _prepare_local_dir(path, AgentRuntimeConfig("vega", "Private project instructions"), "model-a", None, None, 128_000)


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory permissions")
def test_local_store_refuses_shared_directory(tmp_path):
    path = tmp_path / "shared"
    path.mkdir(mode=0o755)
    path.chmod(0o755)
    with pytest.raises(ValueError, match="private"):
        _prepare_local_dir(path, AgentRuntimeConfig("orion", "Instructions"), "model", None, None, 128_000)


def _host(tmp_path, declared, installed=None, name=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"libfx": declared}}))
    if installed is not None:
        (tmp_path / "node_modules" / "libfx").mkdir(parents=True)
        manifest = {"name": name or ("@kunemi-group/kai" if "-kai." in installed else "libfx"), "version": installed}
        (tmp_path / "node_modules" / "libfx" / "package.json").write_text(json.dumps(manifest))
    return tmp_path


def test_the_fx_host_runs_only_an_admitted_libfx_artifact(tmp_path):
    from dotrix_engine.runtimes.fx import LIBFX_ARTIFACTS, installed_libfx_version, libfx_version

    assert libfx_version() in LIBFX_ARTIFACTS  # the repository's own pin is admitted
    assert libfx_version(_host(tmp_path / "pinned", "0.0.16")) == "0.0.16"
    with pytest.raises(RuntimeError, match="not an admitted"):
        libfx_version(_host(tmp_path / "unknown", "9.9.9"))
    assert installed_libfx_version(_host(tmp_path / "absent", "0.0.16")) is None
    assert installed_libfx_version(_host(tmp_path / "other", "0.0.16", installed="0.0.17")) == "0.0.17"


def test_the_kai_runtime_is_admitted_only_as_its_own_package(tmp_path):
    """The Kai runtime's versions are @kunemi-group/kai on GitHub Packages, installed under the name libfx; fx's
    releases are libfx on npm. A host naming either under the other's package is refused."""
    from dotrix_engine.runtimes.fx import LIBFX_ARTIFACTS, installed_libfx_version, libfx_version

    assert LIBFX_ARTIFACTS["0.0.17-kai.1"] == ("0.0.16",)
    assert LIBFX_ARTIFACTS["0.0.17-kai.2"] == ("0.0.17-kai.1", "0.0.16")
    assert LIBFX_ARTIFACTS["0.0.17-kai.3"] == ("0.0.17-kai.2", "0.0.17-kai.1", "0.0.16")
    assert LIBFX_ARTIFACTS["0.0.18-kai.1"] == ("0.0.17-kai.3", "0.0.17-kai.2", "0.0.17-kai.1", "0.0.16")
    assert LIBFX_ARTIFACTS["0.0.18-kai.2"] == ("0.0.18-kai.1", "0.0.17-kai.3", "0.0.17-kai.2", "0.0.17-kai.1", "0.0.16")
    kai = "npm:@kunemi-group/kai@0.0.17-kai.1"
    assert libfx_version(_host(tmp_path / "kai", kai)) == "0.0.17-kai.1"
    assert installed_libfx_version(_host(tmp_path / "kai-installed", kai, installed="0.0.17-kai.1")) == "0.0.17-kai.1"
    for refused in ("0.0.17-kai.1", "npm:@someone/kai@0.0.17-kai.1", "npm:@kunemi-group/kai@0.0.16"):
        with pytest.raises(RuntimeError):
            libfx_version(_host(tmp_path / refused.replace("/", "_").replace("@", "_").replace(":", "_"), refused))
    # A package other than the one its version is published as, installed in its place.
    for name, version in (("libfx", "0.0.17-kai.1"), ("@kunemi-group/kai", "0.0.16"), ("@someone/kai", "0.0.17-kai.1")):
        with pytest.raises(RuntimeError, match="not a libfx artifact"):
            installed_libfx_version(_host(tmp_path / f"{name}-{version}".replace("/", "_"), kai, installed=version, name=name))


async def test_the_fx_host_refuses_an_install_that_differs_from_its_pin(tmp_path, monkeypatch):
    from dotrix_engine.runtimes import FxRuntime
    from dotrix_engine.runtimes import fx as fx_module

    monkeypatch.setattr(fx_module, "_HOST", _host(tmp_path, "0.0.16", installed="0.0.17"))
    with pytest.raises(RuntimeError, match="0.0.17 is installed but this host pins 0.0.16"):
        await FxRuntime.create(AgentRuntimeConfig("nova", "Answer.", ()), model="test-model")


def test_the_configuration_digest_names_the_pinned_artifact(monkeypatch):
    from dotrix_engine.runtimes import fx as fx_module

    config = AgentRuntimeConfig("nova", "Answer.", ())
    pinned = fx_configuration_digest(config, model="m")
    monkeypatch.setitem(fx_module.LIBFX_ARTIFACTS, "0.0.17-test", ("0.0.16",))
    monkeypatch.setattr(fx_module, "libfx_version", lambda host=None: "0.0.17-test")
    assert fx_configuration_digest(config, model="m") != pinned


def test_the_fx_chat_host_uses_the_environment_s_proxy(tmp_path):
    """libfx calls the provider with Node's fetch, which ignores HTTP(S)_PROXY unless NODE_USE_ENV_PROXY is
    set: the host is started with it, so behind a proxy fx chat goes through it as DeepAgents does."""
    import http.server
    import shutil
    import subprocess
    import threading

    from dotrix_engine.runtimes.fx import host_env

    assert host_env()["NODE_USE_ENV_PROXY"] == "1" and host_env()["PATH"] == os.environ["PATH"]
    node = shutil.which("node")
    if node is None:
        pytest.skip("node isn't installed")
    seen: list[str] = []

    class Proxy(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_CONNECT(self):  # Node 24 tunnels even a plain http:// request, as it does to an HTTPS provider
            seen.append(self.path)
            self.send_response(200)
            self.end_headers()
            while self.rfile.readline() not in (b"\r\n", b""):  # the tunnelled request, answered here
                pass
            self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            self.close_connection = True

        def do_GET(self):  # Node 26 sends a plain http:// request to the proxy as an absolute-form GET
            seen.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        proxy = f"http://127.0.0.1:{server.server_port}"
        env = {**host_env(), "HTTP_PROXY": proxy, "http_proxy": proxy, "NO_PROXY": "", "no_proxy": ""}
        script = "fetch('http://provider.invalid/v1/models').then(r => r.text()).then(t => console.log(t))"
        done = subprocess.run([node, "-e", script], env=env, capture_output=True, text=True, timeout=30)
    finally:
        server.shutdown()
    # Either way the request reached the proxy, not the provider: provider.invalid has no address.
    assert done.stdout.strip() == "ok", done.stderr[-500:]
    assert seen in (["provider.invalid:80"], ["http://provider.invalid/v1/models"]), seen


async def test_fx_runtime_validates_and_propagates_correlation_id(tmp_path):
    import http.server
    import shutil
    import threading

    from dotrix_engine.runtimes import FxRuntime
    from dotrix_engine.runtimes.contracts import validate_correlation_id
    from dotrix_engine.runtimes.fx import installed_libfx_version, libfx_version

    validate_correlation_id("dotrix-run:42/step:1")
    for bad in ("", "x" * 257, "a\nb", "a\x7fb"):
        with pytest.raises(ValueError, match="Correlation ID"):
            validate_correlation_id(bad)

    node = shutil.which("node")
    if node is None or installed_libfx_version() != libfx_version():
        pytest.skip("node or pinned libfx addon is not installed")

    class Model(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            base = {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": body["model"]}
            chunks = [
                {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"}, "finish_reason": None}]},
                {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            ]
            payload = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(payload.encode())

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        config = AgentRuntimeConfig("nova", "Answer concisely.", ())
        runtime = await FxRuntime.create(
            config, model="test-model", base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="synthetic", engine_session="sess-corr-1", ephemeral_engine=True,
        )
        try:
            with pytest.raises(ValueError, match="Correlation ID"):
                await runtime.prompt("sess-corr-1", "Hi", correlation_id="bad\nvalue")
            seen = []
            async def on_event(event):
                seen.append(event)
            result = await runtime.prompt("sess-corr-1", "Hi", on_event=on_event, correlation_id="run-corr-42")
            assert result.text == "ok"
            assert result.correlation_id == "run-corr-42"
            assert seen and all(ev.correlation_id == "run-corr-42" for ev in seen)

            plain = await runtime.prompt("sess-corr-1", "Again")
            assert plain.correlation_id is None
        finally:
            await runtime.close()
    finally:
        server.shutdown()


async def test_fx_runtime_recovers_saved_write_once_and_preserves_correlation_id_across_restart():
    """D7 durable recovery: a saved side-effecting tool result replays once without re-running on resume,
    and `correlation_id` survives across process restart."""
    import http.server
    import shutil
    import threading

    from dotrix_engine.runtimes import FxRuntime, RuntimeJournalSnapshot, RuntimeTool
    from dotrix_engine.runtimes.fx import installed_libfx_version, libfx_version

    node = shutil.which("node")
    if node is None or installed_libfx_version() != libfx_version():
        pytest.skip("node or pinned libfx addon is not installed")

    class MemoryJournal:
        def __init__(self) -> None:
            self.records: list[tuple[str, bytes]] = []
            self.checkpoint: tuple[str, bytes] | None = None
            self.keys: dict[str, str] = {}
            self.result_saved = asyncio.Event()

        async def load(self) -> RuntimeJournalSnapshot:
            return RuntimeJournalSnapshot(checkpoint=self.checkpoint, records=tuple(self.records))

        async def append(self, *, expected: str | None, idempotency_key: str, data: bytes) -> str:
            if idempotency_key in self.keys:
                return self.keys[idempotency_key]
            current = self.records[-1][0] if self.records else None
            if expected != current:
                raise ValueError(f"Expected cursor {current}, got {expected}")
            cursor = str(len(self.records) + 1)
            self.records.append((cursor, data))
            self.keys[idempotency_key] = cursor
            payload = json.loads(data)
            if any(ev.get("type") == "tool_result" for ev in payload.get("events", [])):
                self.result_saved.set()
            return cursor

        async def save_checkpoint(self, *, through: str, data: bytes) -> None:
            self.checkpoint = (through, data)

    gate = threading.Event()
    gate.set()

    class Model(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            gate.wait(timeout=15)
            tool_msg = next((m for m in reversed(body["messages"]) if m["role"] == "tool"), None)
            if tool_msg is None:
                delta = {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call-write-1",
                            "type": "function",
                            "function": {"name": "write_note", "arguments": json.dumps({"text": "saved-once"})},
                        }
                    ],
                }
                finish = "tool_calls"
            else:
                delta, finish = {"role": "assistant", "content": f"Confirmed: {tool_msg['content']}"}, "stop"
            base = {"id": "c-d7", "object": "chat.completion.chunk", "created": 1, "model": body["model"]}
            chunks = [
                {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
            ]
            payload = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(payload.encode())

    executions: list[str] = []

    async def write_note(arguments: dict, context) -> str:
        executions.append(context.execution_id)
        gate.clear()  # Pause the follow-up model call so we kill the host right after journaling tool_result.
        return f"wrote:{arguments['text']}:{len(executions)}"

    config = AgentRuntimeConfig(
        "nova",
        "Record notes.",
        (
            RuntimeTool(
                "write_note",
                "Write a note once",
                {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                execute_scoped=write_note,
                writes=True,
            ),
        ),
    )
    journal = MemoryJournal()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/v1"
        first = await FxRuntime.create(
            config, model="test-model", base_url=url, api_key="synthetic",
            journal=journal, engine_session="sess-d7-1",
        )
        task = asyncio.create_task(
            first.prompt("sess-d7-1", "Save note", message_id="turn-d7-1", correlation_id="run-d7-99")
        )
        try:
            await asyncio.wait_for(journal.result_saved.wait(), 20)
        finally:
            first.process.kill()
            gate.set()
        with pytest.raises(RuntimeError):
            await task
        await first.close()

        assert len(executions) == 1
        resumed_events = []

        async def on_event(event):
            resumed_events.append(event)

        second = await FxRuntime.create(
            config, model="test-model", base_url=url, api_key="synthetic",
            journal=journal, engine_session="sess-d7-1",
        )
        try:
            resumed = await asyncio.wait_for(
                second.resume("sess-d7-1", rerun_tools=(), correlation_id="run-d7-99", on_event=on_event),
                30,
            )
            assert resumed.stop_reason == "end_turn"
            assert "wrote:saved-once:1" in resumed.text
            assert resumed.correlation_id == "run-d7-99"
            assert resumed_events and all(ev.correlation_id == "run-d7-99" for ev in resumed_events)
            assert len(executions) == 1
        finally:
            await second.close()
    finally:
        gate.set()
        server.shutdown()
