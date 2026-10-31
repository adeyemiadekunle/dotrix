"""Nova thinks before it answers, and the stream carries what it thought apart from its reply."""
import asyncio
import uuid

from dotrix_backend.modules.agents.llm import thinking_options
from dotrix_backend.modules.agents.streams import RunStreams, text_of, thinking_of
from dotrix_engine.agent import DECIDE_GUIDE


def test_thinking_comes_from_anthropic_thinking_and_openai_reasoning_summaries() -> None:
    content = [{"type": "thinking", "thinking": "Weigh it. ", "signature": "s"},
               {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Then decide."}]},
               {"type": "redacted_thinking", "data": "x"}, {"type": "text", "text": "Paris."}]
    assert thinking_of(content) == "Weigh it. Then decide."
    assert text_of(content) == "Paris."
    assert thinking_of("Paris.") == ""


def test_nova_s_model_thinks_and_shows_it_where_the_provider_can() -> None:
    effort = {"anthropic": "high", "openai": "medium"}
    assert thinking_options("anthropic:claude-haiku-5-5", effort) == {
        "thinking": {"type": "adaptive", "display": "summarized"}, "output_config": {"effort": "high"},
        "max_tokens": 16_000}
    assert thinking_options("openai:gpt-5.5", effort) == {
        "use_responses_api": True, "reasoning": {"effort": "medium", "summary": "auto"}}
    assert thinking_options("anthropic:claude-haiku-4-5-20251001", effort) == {}  # a token budget, not adaptive
    assert thinking_options("xai:grok-4.7", effort) == {}
    assert thinking_options("anthropic:claude-haiku-5-5", {}) == {}  # off: the provider's defaults


async def test_a_follower_gets_the_thinking_so_far_then_each_new_piece() -> None:
    streams, run_id = RunStreams(), uuid.uuid4()
    stream = await streams.open(run_id)
    await stream.think("Not about the project. ")
    seen: list[tuple[str, str]] = []

    async def follow() -> None:
        async for event in streams.follow(run_id):
            seen.append(event)

    task = asyncio.create_task(follow())
    await asyncio.sleep(0)
    await stream.think("Answer directly.")
    await stream.publish("Paris.")
    await streams.close(run_id)
    await task
    assert seen == [("text", ""), ("thinking_text", "Not about the project. "), ("thinking", "Answer directly."),
                    ("delta", "Paris."), ("end", "")]


def test_nova_decides_before_reading_or_delegating() -> None:
    assert "capital" in DECIDE_GUIDE and "Don't read, search, or delegate" in DECIDE_GUIDE
