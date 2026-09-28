"""Counting an agent run's tokens."""
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from pmagent_backend.modules.agents.usage import TokenUsage
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
    assert counter.take() == {"input_tokens": 7, "output_tokens": 2, "cached_input_tokens": 0, "model_calls": 1}
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
