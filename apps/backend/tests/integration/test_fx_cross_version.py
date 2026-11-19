"""A journal written by one libfx artifact, read by another, through the real host and Postgres.

Opt-in: set DOTRIX_FX_WRITER_HOST and DOTRIX_FX_READER_HOST to two copies of the fx host
(`runtimes/fx_host` with its own `npm ci`), each with the libfx artifact under test installed. The
writer's journal must be readable by the reader before a pin change admits saved runs to the reader;
swap them to check what rollback would read. Unset, these tests skip.
"""
import asyncio
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from dotrix_backend.modules.agents.runtime_tools import RuntimeRunScope, scoped_knowledge_tools
from dotrix_engine.builtins import builtin
from dotrix_engine.runtimes import AgentRuntimeConfig, FxRuntime
from dotrix_engine.runtimes import fx as fx_module

from . import test_runtime_tools as shared

# The real-host fixtures this module shares with test_runtime_tools.
journal_world, nova_pilot_world, model_server = shared.journal_world, shared.nova_pilot_world, shared.model_server

_WRITER = os.environ.get("DOTRIX_FX_WRITER_HOST")
_READER = os.environ.get("DOTRIX_FX_READER_HOST")

pytestmark = pytest.mark.skipif(not (_WRITER and _READER and shutil.which("node")),
                                reason="Set DOTRIX_FX_WRITER_HOST and DOTRIX_FX_READER_HOST to two fx host installs")


def _version(host: str) -> str:
    return json.loads((Path(host) / "node_modules" / "libfx" / "package.json").read_text())["version"]


async def _runtime(monkeypatch, host: str, config, url, journal):
    # This test is the evidence for an entry in LIBFX_ARTIFACTS, so it admits the artifacts it compares.
    version = json.loads((Path(host) / "package.json").read_text())["dependencies"]["libfx"]
    if version not in fx_module.LIBFX_ARTIFACTS:
        monkeypatch.setitem(fx_module.LIBFX_ARTIFACTS, version, ())
    monkeypatch.setattr(fx_module, "_HOST", Path(host))
    return await FxRuntime.create(config, model="test-model", base_url=url, api_key="test-key",
                                  journal=journal, engine_session="journal-session")


def _read_tool(run, sessions):
    scope = RuntimeRunScope(run.workspace_id, run.project_id, run.id, run.requested_by_id,
                            "project-manager", 1, "journal-session")
    return next(tool for tool in scoped_knowledge_tools(sessions, scope=scope, spec=builtin("project-manager"),
                                                        embedder=None) if tool.name == "read_section")


async def test_a_completed_turn_is_repeated_from_the_other_artifacts_journal(journal_world, monkeypatch):
    """Retrying a finished turn's ID returns its saved answer: no model request, no tool call."""
    run, sessions, _, _, journal = journal_world
    read = _read_tool(run, sessions)
    executions = []

    async def counted(arguments, context):
        executions.append(context.execution_id)
        return await read.execute_scoped(arguments, context)

    config = AgentRuntimeConfig("project-manager", "Use the project knowledge tool.",
                                (replace(read, execute_scoped=counted),))
    requests = []
    with model_server(requests=requests, report_usage=True) as url:
        first = await _runtime(monkeypatch, _WRITER, config, url, journal)
        try:
            written = await asyncio.wait_for(first.prompt("journal-session", "Read the evidence", message_id="turn-1"), 30)
        finally:
            await first.close()
        assert "Private project evidence" in written.text and len(executions) == 1
        before = len(requests)
        second = await _runtime(monkeypatch, _READER, config, url, journal)
        try:
            repeated = await asyncio.wait_for(second.prompt("journal-session", "Read the evidence", message_id="turn-1"), 30)
            assert repeated.text == written.text
            assert len(requests) == before and len(executions) == 1
            # The next turn continues the same history on the reader.
            follow = await asyncio.wait_for(second.prompt("journal-session", "And again", message_id="turn-2"), 30)
            assert "Private project evidence" in follow.text
            history = requests[-1]["request"]["messages"]
            assert any(m["role"] == "user" and "Read the evidence" in str(m.get("content")) for m in history)
        finally:
            await second.close()
    print(f"\n{_version(_WRITER)} -> {_version(_READER)}: completed turn repeated, follow-up continued")


async def test_an_interrupted_read_resumes_on_the_other_artifact(journal_world, monkeypatch):
    """A writer killed after saving a tool intent is resumed by the reader with the same execution ID."""
    run, sessions, _, _, journal = journal_world
    read = _read_tool(run, sessions)
    intent_saved = asyncio.Event()
    original_append = journal.append

    async def observe_append(**kwargs):
        cursor = await original_append(**kwargs)
        record = json.loads(kwargs["data"])
        if any(event["type"] == "tool_intent" and any(call["name"] == "read_section" for call in event["data"])
               for event in record["events"]):
            intent_saved.set()
        return cursor

    monkeypatch.setattr(journal, "append", observe_append)
    started = asyncio.Event()
    recovered = False
    executions = []

    async def interrupted_read(arguments, context):
        executions.append(context.execution_id)
        if not recovered:
            started.set()
            await asyncio.Event().wait()
        return await read.execute_scoped(arguments, context)

    config = AgentRuntimeConfig("project-manager", "Use the project knowledge tool.",
                                (replace(read, execute_scoped=interrupted_read),))
    with model_server(report_usage=True) as url:
        first = await _runtime(monkeypatch, _WRITER, config, url, journal)
        task = asyncio.create_task(first.prompt("journal-session", "Read the evidence", message_id="turn-1"))
        try:
            await asyncio.wait_for(started.wait(), 20)
            await asyncio.wait_for(intent_saved.wait(), 20)
        finally:
            first.process.kill()
        with pytest.raises(RuntimeError):
            await task
        await first.close()
        recovered = True
        second = await _runtime(monkeypatch, _READER, config, url, journal)
        try:
            result = await asyncio.wait_for(second.resume("journal-session", rerun_tools=("read_section",)), 30)
            assert result.stop_reason == "end_turn" and "Private project evidence" in result.text
            assert len(executions) == 2 and executions[0] == executions[1]
        finally:
            await second.close()
    print(f"\n{_version(_WRITER)} -> {_version(_READER)}: interrupted read resumed once")


@pytest.mark.parametrize("final_finish", ["length", "content_filter"])
async def test_a_cut_off_answer_is_never_repeated_as_complete(journal_world, monkeypatch, final_finish):
    """An answer the provider cut off (output limit, content filter) stays incomplete on a retry by ID.

    libfx 0.0.17 settles an output-limit turn as `max_output_tokens`. A reader that keeps that outcome
    reports it again; one that predates it must refuse the journal rather than call the answer complete.
    Published 0.0.17 never recorded the outcome, so its journals fail this on every reader."""
    run, sessions, _, _, journal = journal_world
    config = AgentRuntimeConfig("project-manager", "Use the project knowledge tool.", (_read_tool(run, sessions),))
    requests = []
    with model_server(requests=requests, final_finish=final_finish) as url:
        first = await _runtime(monkeypatch, _WRITER, config, url, journal)
        try:
            try:
                cut = await first.prompt("journal-session", "Read the evidence", message_id="turn-1")
            except RuntimeError:
                cut = None
            assert cut is None or cut.stop_reason != "end_turn"
        finally:
            await first.close()
        calls = len(requests)
        try:
            second = await _runtime(monkeypatch, _READER, config, url, journal)
        except RuntimeError:
            print(f"\n{_version(_WRITER)} -> {_version(_READER)}: the reader refused the journal")
            return
        try:
            try:
                retried = await second.prompt("journal-session", "Read the evidence", message_id="turn-1")
            except RuntimeError:
                retried = None
            assert retried is None or retried.stop_reason != "end_turn", (
                f"{_version(_WRITER)} -> {_version(_READER)} repeated a cut-off answer as complete")
            assert len(requests) == calls
        finally:
            await second.close()
