"""run_script: code mode for dotrix's own agents (agents/scripts.py), on the real Monty sandbox."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from langchain_core.tools import StructuredTool

from dotrix_backend.core.errors import Conflict, Forbidden, NotFound
from dotrix_backend.modules.agents.scripts import (
    LIMITS,
    MAX_RESULT,
    SCRIPT_TOOL,
    ScriptAborted,
    ScriptFunctionSpec,
    run_script,
    script_runtime_tool,
    script_tool,
)
from dotrix_engine.runtimes import RuntimeTool, RuntimeToolContext

QUERY = {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 8}},
         "required": ["query"]}


def _functions(**calls: Any) -> dict[str, ScriptFunctionSpec]:
    return {name: ScriptFunctionSpec(name, f"{name} does a thing.", QUERY, call) for name, call in calls.items()}


async def _search(args: dict) -> dict:
    await asyncio.sleep(0.2)
    return {"hits": [{"path": f"/dotrix/{args['query']}-{i}.md", "score": i} for i in range(args.get("limit", 5))]}


def test_a_script_chains_reads_runs_them_at_once_and_returns_only_what_it_keeps() -> None:
    seen: list[tuple[str, dict]] = []

    async def on_call(name: str, args: dict) -> None:
        seen.append((name, args))

    code = (
        "import asyncio\n"
        "found = await asyncio.gather(search(query='payments'), search(query='refunds'), search(query='tax'))\n"
        "paths = [h['path'] for r in found for h in r['hits'] if h['score'] >= 3]\n"
        "print('kept', len(paths))\n"
        "paths"
    )
    started = time.monotonic()
    said = asyncio.run(run_script(code, _functions(search=_search), on_call=on_call))
    assert time.monotonic() - started < 0.55  # three 0.2 s calls together, not one after another
    assert "Printed:\nkept 6" in said and '"/dotrix/payments-3.md"' in said and "payments-0" not in said
    assert said.endswith("(3 tool calls)")
    assert [name for name, _ in seen] == ["search"] * 3 and {"query": "tax"} in [args for _, args in seen]


@pytest.mark.parametrize("code", [
    "open('/etc/passwd').read()",
    "from pathlib import Path\nPath('/etc/passwd').read_text()",
    "import os\nos.listdir('/')",
    "import os\ndict(os.environ)",
    "import subprocess\nsubprocess.run(['id'])",
    "import socket\nsocket.socket()",
    "import urllib.request\nurllib.request.urlopen('https://example.com')",
    "__import__('os')",
    "exec(\"r = open('/etc/passwd').read()\")\nr",
    "().__class__.__mro__[-1].__subclasses__()",
    "(lambda: 0).__globals__",
])
def test_the_sandbox_has_no_files_network_environment_or_way_out(code: str) -> None:
    said = asyncio.run(run_script(code, {}))
    assert said.startswith("The script failed:") and "root:" not in said


def test_the_limits_stop_a_script_and_say_why() -> None:
    assert "TimeoutError" in asyncio.run(run_script("while True:\n    pass", {}))
    assert "MemoryError" in asyncio.run(run_script("x = 'a' * (10**10)", {}))

    async def quick(args: dict) -> int:
        return 1
    many = asyncio.run(run_script("for i in range(100):\n    await f(query=str(i))\n'done'", _functions(f=quick)))
    assert f"suspension limit {LIMITS['max_suspensions']} exceeded" in many and "(40 tool calls)" in many


def test_a_large_result_is_cut_and_says_to_filter() -> None:
    said = asyncio.run(run_script("'x' * 50000", {}))
    assert "more characters cut: return less, or filter it in the script" in said
    assert len(said) < MAX_RESULT + 300


@pytest.mark.parametrize("refusal", [Conflict("The run no longer owns this work"),
                                     Forbidden("The person who asked no longer sees this project")])
def test_losing_the_work_or_access_ends_the_script_even_if_the_code_catches_it(refusal: Exception) -> None:
    calls = []

    async def refused(args: dict) -> None:
        calls.append(args)
        raise refusal

    code = "for i in range(5):\n    try:\n        await f(query=str(i))\n    except Exception:\n        pass\n'carried on'"
    with pytest.raises(ScriptAborted) as aborted:
        asyncio.run(run_script(code, _functions(f=refused)))
    assert aborted.value.__cause__ is refusal and len(calls) == 1  # no call after the first refusal


def test_another_tool_failure_reaches_the_script_which_may_handle_it() -> None:
    async def missing(args: dict) -> None:
        raise NotFound("No issue KUN-404")

    said = asyncio.run(run_script(
        "try:\n    await f(query='KUN-404')\nexcept Exception as e:\n    r = 'not there: ' + str(e)\nr", _functions(f=missing)))
    assert "not there: No issue KUN-404" in said
    plain = asyncio.run(run_script("await f('positional')", _functions(f=missing)))
    assert "Call f with keyword arguments" in plain


def _structured(name: str, fn) -> StructuredTool:
    return StructuredTool.from_function(coroutine=fn, name=name, description=f"{name}.")


async def _read(file_path: str) -> dict:
    return {"path": file_path, "content": "hello"}


async def _write(file_path: str, content: str) -> dict:
    raise AssertionError("a script must never reach a write")


def test_deepagents_scripts_get_only_the_reads_the_contract_allows() -> None:
    allowed = {"knowledge.read", "board.read"}
    tools = [_structured("read_file", _read), _structured("write_file", _write), _structured("list_issues", _read),
             _structured("create_issue", _write), _structured("link_items", _write), _structured("web_search", _read),
             _structured("graph_neighbors", _read), _structured("code_read", _read)]
    tool = script_tool(tools, can=lambda capability: capability in allowed)
    assert tool is not None and tool.name == SCRIPT_TOOL
    assert "await read_file(file_path: str)" in tool.description and "await list_issues(" in tool.description
    for absent in ("write_file", "create_issue", "link_items", "web_search", "graph_neighbors", "code_read"):
        assert f"await {absent}(" not in tool.description
    said = asyncio.run(tool.ainvoke({"code": "r = await read_file(file_path='/dotrix/a.md')\nr['content']"}))
    assert "Result:\nhello" in said
    refused = asyncio.run(tool.ainvoke({"code": "await write_file(file_path='/dotrix/a.md', content='x')"}))
    assert "NameError" in refused  # not there at all
    assert script_tool([_structured("write_file", _write)], can=lambda _: True) is None


def test_fx_scripts_call_the_turn_s_own_tools_with_its_context_and_raise_a_lost_lease() -> None:
    contexts: list[RuntimeToolContext] = []
    lost = [False]

    async def read(arguments: dict, context: RuntimeToolContext) -> dict:
        contexts.append(context)
        if lost[0]:
            raise Conflict("The run no longer owns this work")
        return {"content": arguments["file_path"]}

    async def write(arguments: dict, context: RuntimeToolContext) -> dict:
        raise AssertionError("a script must never reach a write")

    schema = {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}
    tools = [RuntimeTool("read_file", "Read.", schema, execute_scoped=read, idempotent=True, writes=False),
             RuntimeTool("write_file", "Write.", schema, execute_scoped=write, writes=True),
             RuntimeTool("web_search", "Search the web.", schema, execute_scoped=read, writes=False)]
    tool = script_runtime_tool(tools)
    assert tool is not None and not tool.writes and tool.idempotent
    assert "await read_file(" in tool.description and "write_file" not in tool.description and "web_search" not in tool.description
    context = RuntimeToolContext(session_id="fx-pilot-1", execution_id="call-1")
    assert tool.execute_scoped is not None
    said = asyncio.run(tool.execute_scoped({"code": "(await read_file(file_path='/a.md'))['content']"}, context))
    assert "/a.md" in said and contexts == [context]
    lost[0] = True
    with pytest.raises(Conflict):
        asyncio.run(tool.execute_scoped({"code": "await read_file(file_path='/a.md')"}, context))
