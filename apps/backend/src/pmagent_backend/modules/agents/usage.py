"""Token usage of an agent run, counted from every model call it makes (feeds FR-28 spend
limits, and shows when a model stopped early: an empty reply with zero output tokens)."""
from __future__ import annotations

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult


class TokenUsage(BaseCallbackHandler):
    """Adds up the input and output tokens of every model call it sees.

    Given in a graph's config (`callbacks`), it's inherited by child runs, so tool calls and
    the subagents the `task` tool starts are counted too. Unlike langchain's
    `UsageMetadataCallbackHandler`, it counts calls whose response has no model name (the
    scripted test models) and keeps one total rather than one per model.

    `on_llm_end` gets the whole message even when the model streams, so chunks aren't counted
    twice.
    """

    run_inline = True

    def __init__(self) -> None:
        super().__init__()
        self._reset()

    def _reset(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        # Input tokens the provider served from its prompt cache (billed at a fraction): the
        # part of each prompt that repeats, like the instructions and the context pack.
        self.cached_input_tokens = 0
        # Each call re-sends the whole prompt, so fewer steps is the other big saving.
        self.model_calls = 0

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        self.model_calls += 1
        for generations in response.generations:
            for generation in generations:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None)
                if usage:
                    self.input_tokens += int(usage.get("input_tokens") or 0)
                    self.output_tokens += int(usage.get("output_tokens") or 0)
                    details = usage.get("input_token_details") or {}
                    self.cached_input_tokens += int(details.get("cache_read") or 0)

    def details(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "model_calls": self.model_calls,
        }

    def take(self) -> dict[str, int]:
        """The counts so far, starting again from zero, so tokens already recorded on the run
        aren't added twice."""
        details = self.details()
        self._reset()
        return details
