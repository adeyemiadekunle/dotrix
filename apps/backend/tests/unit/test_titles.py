"""Conversation titles: the placeholder and cleaning up what the model returns."""
import asyncio
from types import SimpleNamespace

from pmagent_backend.modules.agents.titles import generate_title, placeholder_title


def test_placeholder_is_the_first_sentence_trimmed() -> None:
    assert placeholder_title("what should we build next? Also, the roadmap.") == "What should we build next"
    long = "Please create a low-priority task under epic KLL-1 titled add a zone analytics dashboard"
    assert placeholder_title(long) == "Please create a low-priority task under epic KLL-1…"
    assert placeholder_title("   ") == "New conversation"


class FakeModel:
    def __init__(self, content=None, error: Exception | None = None, delay: float = 0) -> None:
        self.content, self.error, self.delay = content, error, delay

    async def ainvoke(self, prompt: str):
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.content)


async def test_generated_titles_are_cleaned() -> None:
    assert await generate_title(FakeModel('"board status and blockers."'), "m", "r") == "Board status and blockers"
    blocks = [{"type": "text", "text": "Multi-zone driver epic\nextra line"}]
    assert await generate_title(FakeModel(blocks), "m", "r") == "Multi-zone driver epic"


async def test_failures_keep_the_placeholder() -> None:
    assert await generate_title(FakeModel(error=RuntimeError("quota")), "m", "r") is None
    assert await generate_title(FakeModel(""), "m", "r") is None
