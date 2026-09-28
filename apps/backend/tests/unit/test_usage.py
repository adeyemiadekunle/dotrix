"""Counting an agent run's tokens."""
import uuid

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from pmagent_backend.modules.agents.usage import TokenBudgetExceeded, TokenUsage, merge_breakdown
from pmagent_engine.testing import ScriptedChatModel, tool_call


def usage(input_tokens: int, output_tokens: int) -> dict[str, int]:
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens}


def test_adds_up_every_generation() -> None:
    counter = TokenUsage()
    counter.on_llm_end(
        LLMResult(
            generations=[
                [ChatGeneration(message=AIMessage(content="a", usage_metadata=usage(10, 3)))],
                [
                    ChatGeneration(message=AIMessage(content="b", usage_metadata=usage(5, 0))),
                    ChatGeneration(message=AIMessage(content="no usage reported")),
                ],
            ]
        )
    )
    counter.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content="c", usage_metadata=usage(1, 2)))]]))
    assert counter.details() == {"input_tokens": 16, "output_tokens": 5, "cached_input_tokens": 0, "model_calls": 2}


def test_take_starts_again_from_zero() -> None:
    counter = TokenUsage()
    counter.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content="a", usage_metadata=usage(7, 2)))]]))
    totals, breakdown = counter.take()
    assert totals == {"input_tokens": 7, "output_tokens": 2, "cached_input_tokens": 0, "model_calls": 1}
    assert breakdown["by_agent"] == {}  # no model start seen: counted in the totals only
    assert counter.details() == {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0, "model_calls": 0}


async def test_streamed_calls_are_counted_once() -> None:
    reply = tool_call("read_file", file_path="/pmagent/x.md")
    reply.usage_metadata = usage(20, 4)  # type: ignore[assignment]
    model = ScriptedChatModel.of(
        AIMessage(content="several words streamed one by one", usage_metadata=usage(10, 3)),
        reply,
        AIMessage(content=[], usage_metadata=usage(8, 0)),  # an empty turn still costs input
        "no usage reported",
    )
    counter = TokenUsage()
    for _ in range(4):
        async for _chunk in model.astream("hi", config={"callbacks": [counter]}):
            pass
    assert counter.details() == {"input_tokens": 38, "output_tokens": 7, "cached_input_tokens": 0, "model_calls": 4}


def test_cached_input_tokens_are_counted() -> None:
    counter = TokenUsage()
    cached = usage(1_000, 50) | {"input_token_details": {"cache_read": 800}}
    counter.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content="a", usage_metadata=cached))]]))
    counter.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content="b", usage_metadata=usage(200, 5)))]]))
    assert counter.details() == {"input_tokens": 1_200, "output_tokens": 55, "cached_input_tokens": 800, "model_calls": 2}


async def test_by_agent_tools_and_files_read() -> None:
    counter = TokenUsage()
    pm, research = uuid.uuid4(), uuid.uuid4()
    counter.on_chat_model_start({}, [], run_id=pm, metadata={})
    counter.on_chat_model_start({}, [], run_id=research, metadata={"lc_agent_name": "research-agent"})
    result = LLMResult(generations=[[ChatGeneration(message=AIMessage(content="a", usage_metadata=usage(100, 10)))]])
    counter.on_llm_end(result, run_id=research)
    counter.on_llm_end(result, run_id=pm)
    counter.on_llm_end(result, run_id=pm)  # a call whose start wasn't seen goes to the PM
    read = uuid.uuid4()
    counter.on_tool_start({"name": "read_file"}, "", run_id=read, inputs={"file_path": "/pmagent/roadmap.md"})
    counter.on_tool_end("x" * 400, run_id=read)
    task = uuid.uuid4()
    counter.on_tool_start({"name": "task"}, "", run_id=task, inputs={"description": "research it"})
    counter.on_tool_end(AIMessage(content="y" * 40), run_id=task)
    breakdown = counter.breakdown()
    assert breakdown["by_agent"] == {
        "research": {"input_tokens": 100, "output_tokens": 10, "model_calls": 1},
        "project-manager": {"input_tokens": 200, "output_tokens": 20, "model_calls": 2},
    }
    assert breakdown["tools"] == {
        "read_file": {"calls": 1, "result_tokens": 100},
        "task": {"calls": 1, "result_tokens": 10},
    }
    assert breakdown["files_read"] == {"/pmagent/roadmap.md": 1}


async def test_the_budget_stops_the_next_model_call() -> None:
    model = ScriptedChatModel.of(
        AIMessage(content="one", usage_metadata=usage(60, 5)), AIMessage(content="two", usage_metadata=usage(60, 5))
    )
    counter = TokenUsage(budget=100, used=30)  # earlier steps of the run count
    async for _chunk in model.astream("hi", config={"callbacks": [counter]}):
        pass
    assert counter.used == 95  # under the budget: the next call may start
    counter.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content="b", usage_metadata=usage(5, 0)))]]))
    with pytest.raises(TokenBudgetExceeded) as raised:
        async for _chunk in model.astream("hi", config={"callbacks": [counter]}):
            pass
    assert (raised.value.used, raised.value.budget) == (100, 100)


def test_no_budget_never_stops() -> None:
    counter = TokenUsage(budget=None, used=10**9)
    counter.on_chat_model_start({}, [], run_id=uuid.uuid4())


def test_breakdowns_add_up_over_steps() -> None:
    first = {"by_agent": {"project-manager": {"input_tokens": 5, "output_tokens": 1, "model_calls": 1}},
             "tools": {"read_file": {"calls": 1, "result_tokens": 50}}, "files_read": {"/pmagent/a.md": 1}}
    second = {"by_agent": {"project-manager": {"input_tokens": 7, "output_tokens": 2, "model_calls": 1},
                           "product": {"input_tokens": 3, "output_tokens": 1, "model_calls": 1}},
              "tools": {"read_file": {"calls": 2, "result_tokens": 10}}, "files_read": {"/pmagent/a.md": 2, "/pmagent/b.md": 1}}
    merged = merge_breakdown(merge_breakdown({}, first), second)
    assert merged["by_agent"]["project-manager"] == {"input_tokens": 12, "output_tokens": 3, "model_calls": 2}
    assert merged["by_agent"]["product"]["model_calls"] == 1
    assert merged["tools"]["read_file"] == {"calls": 3, "result_tokens": 60}
    assert merged["files_read"] == {"/pmagent/a.md": 3, "/pmagent/b.md": 1}
