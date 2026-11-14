"""Validate measurement boundaries without model calls or a database."""
import uuid
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from apps.backend.tests.integration import test_live_scripts as benchmark
from apps.backend.tests.integration.test_live_scripts import LARGE_FILES, MATCHES, RECORDS
from apps.backend.tests.script_benchmark import instrument, result_bytes
from dotrix_backend.modules.agents import scripts
from dotrix_backend.modules.agents.usage import TokenUsage
from dotrix_engine.runtimes.fx import FxRuntime


def test_corpus_requires_both_predicates_and_contains_large_distractors():
    assert len(RECORDS) == 300
    assert MATCHES == ("CASE-077", "CASE-154", "CASE-231")
    assert any(row["topic"] == "refund" and row["status"] != "blocked" for row in RECORDS)
    assert any(row["topic"] != "refund" and row["status"] == "blocked" for row in RECORDS)
    for i in range(1, 4):
        path = f"research/support-{i}.md"
        assert path in LARGE_FILES["research/support-index.md"]
        assert len(LARGE_FILES[path]) > 50_000  # paging/filtering matters, unlike the tiny control


def test_result_bytes_counts_utf8_content_without_retaining_a_message():
    message = ToolMessage(content="évidence", tool_call_id="read-1")
    assert result_bytes(message) == len("évidence".encode())
    assert result_bytes({"rows": [1, 2]}) == len(b'{"rows": [1, 2]}')


async def test_scripts_count_inner_reads_but_only_outer_result_reaches_deepagents(monkeypatch):
    usage = TokenUsage()
    measured = instrument(monkeypatch)
    data = {"rows": ["noise" * 1000, "keep"]}

    async def read(args):
        # A nested LangChain tool callback must not count as a separate model-visible result.
        usage.on_tool_end(data, run_id=uuid.uuid4())
        return data

    functions = {"read": scripts.ScriptFunctionSpec("read", "read", {}, read)}
    result = await scripts.run_script("value = await read()\nvalue['rows'][1]", functions)
    usage.on_tool_end(result, run_id=uuid.uuid4())
    assert measured.script_invocations == measured.script_read_calls == 1
    assert measured.script_read_result_bytes == result_bytes(data)
    assert measured.model_visible_results == 1
    assert measured.model_visible_result_bytes == result_bytes(result)
    assert measured.model_visible_result_bytes < measured.script_read_result_bytes
    # Reset the script context, including after sandbox errors; ordinary reads still count.
    await scripts.run_script("missing_function()", functions)
    usage.on_tool_end("ordinary", run_id=uuid.uuid4())
    usage.on_tool_end(ToolMessage(content="refused", tool_call_id="failed", status="error"), run_id=uuid.uuid4())
    assert measured.model_visible_results == 2


@pytest.mark.parametrize("strategy", ["natural", "requested"])
async def test_benchmark_balances_fresh_trials_and_preserves_failed_quality_reports(monkeypatch, tmp_path, strategy):
    import json

    from dotrix_backend.core.settings import Settings

    original = Settings.model_construct(agent_scripts=False)
    runner = SimpleNamespace(settings=original)
    requests = []
    closed = []

    class Client:
        async def post(self, url, *, headers, json):
            requests.append((runner.settings.agent_scripts, json))
            # The first answer is wrong; retain it and still execute the rest of the pairs.
            reply = "CASE-001" if len(requests) == 1 else "\n".join(MATCHES)
            return SimpleNamespace(status_code=202, json=lambda: {
                "status": "completed", "reply": reply, "input_tokens": 300,
                "cached_input_tokens": None, "output_tokens": 20, "usage_complete": False,
            })

    class Chat:
        async def __aexit__(self, *args):
            closed.append(True)

    async def add_files(*args):
        pass

    async def live(*args):
        return Chat(), SimpleNamespace(runner=runner, client=Client(), base="/runs", headers={})

    monkeypatch.setenv("DOTRIX_LIVE_SCRIPT_REPEATS", "2")
    monkeypatch.setattr(benchmark, "_add_files", add_files)
    monkeypatch.setattr(benchmark, "_live", live)
    with pytest.raises(AssertionError):
        await benchmark.test_live_script_benchmark(
            (None, None, None), None, None, None, None, None, "deepagents", "nvidia", "test:model",
            "filter", benchmark.FILTER, MATCHES, strategy, monkeypatch, tmp_path,
        )
    assert [enabled for enabled, _ in requests] == [True, False, False, True]
    assert all("thread_id" not in request for _, request in requests)
    if strategy == "natural":
        assert len({request["message"] for _, request in requests}) == 1
    else:
        assert all(("Use run_script" in request["message"]) == enabled for enabled, request in requests)
    assert runner.settings is original and closed == [True]
    report = json.loads((tmp_path / "code-mode-benchmark.json").read_text())
    assert len(report["trials"]) == 4
    assert [row["correct"] for row in report["trials"]] == [False, True, True, True]
    assert all(row["uncached_input_tokens"] is None for row in report["trials"])
    assert all(row["usage_complete"] is False for row in report["trials"])
    assert all(not row["script_adopted"] for row in report["trials"])
    assert "CASE-001" not in json.dumps(report)  # answers and tool contents are not retained


async def test_fx_counts_only_successful_outer_tool_replies_after_send(monkeypatch):
    sent = []

    async def send(self, payload):
        if payload.get("id") == "failed-send":
            raise ConnectionError("bridge closed")
        sent.append(payload)

    monkeypatch.setattr(FxRuntime, "_send", send)
    measured = instrument(monkeypatch)
    runtime = object.__new__(FxRuntime)
    for payload in (
        {"op": "tool_reply", "id": "1", "ok": True, "result": {"kept": 3}},
        {"op": "tool_reply", "id": "2", "ok": False, "error": "refused"},
        {"op": "storage_reply", "id": "3", "ok": True, "result": "private journal"},
        {"op": "tool_reply", "id": "4", "ok": True, "handoff": True},
    ):
        await runtime._send(payload)
    assert len(sent) == 4
    assert measured.model_visible_results == 1
    assert measured.model_visible_result_bytes == result_bytes({"kept": 3})
    try:
        await runtime._send({"op": "tool_reply", "id": "failed-send", "ok": True, "result": "lost"})
    except ConnectionError:
        pass
    else:
        raise AssertionError("A failed send must retain its original failure")
    assert measured.model_visible_results == 1
