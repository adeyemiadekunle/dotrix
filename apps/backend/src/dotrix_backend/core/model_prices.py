"""What a model's tokens cost, for engines that report tokens but no cost (Codex, fx).

USD per million tokens: (input, cached input read, cache write, output). Anthropic's from
platform.claude.com/docs/en/about-claude/pricing (2026-10-31; Haiku 5.5 at its rate for prompts up to
100,000 tokens, 5-minute cache writes); OpenAI's as published for its standard tier (2026-10-31; OpenAI
writes its cache at the input rate). `DOTRIX_MODEL_PRICES` adds to or replaces these, e.g.
`{"openai:gpt-6.1-sol": [5, 0.5, 5, 30]}`. A model without a price gets no cost, never a guess.
"""
from __future__ import annotations

PRICES: dict[str, tuple[float, float, float, float]] = {
    "anthropic:claude-opus-5-5": (4.0, 0.20, 5.0, 20.0),
    "anthropic:claude-sonnet-5-5": (2.0, 0.10, 2.50, 10.0),
    "anthropic:claude-sonnet-5": (2.0, 0.20, 2.50, 10.0),
    "anthropic:claude-haiku-5-5": (0.10, 0.01, 0.125, 0.50),
    "anthropic:claude-haiku-4-5-20251001": (1.0, 0.10, 1.25, 5.0),
    "openai:gpt-5.5": (5.0, 0.50, 5.0, 30.0),
    "openai:gpt-5.4-mini": (0.75, 0.075, 0.75, 4.50),
}


def cost_of(model: str | None, *, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0,
            cache_write_tokens: int = 0, overrides: dict[str, list[float]] | None = None) -> float | None:
    """The cost in USD of a turn's tokens on `model` ("provider:model"); `input_tokens` includes the
    cached reads and writes. None when the model has no price."""
    if not model:
        return None
    price = (overrides or {}).get(model) or PRICES.get(model)
    if price is None or len(price) != 4:
        return None
    fresh, read, write, output = price
    cached, written = max(0, cached_input_tokens), max(0, cache_write_tokens)
    uncached = max(0, input_tokens - cached - written)
    return round((uncached * fresh + cached * read + written * write + output_tokens * output) / 1_000_000, 6)
