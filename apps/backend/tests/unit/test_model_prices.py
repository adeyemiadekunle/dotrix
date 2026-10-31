import json

from dotrix_backend.core.model_prices import cost_of
from dotrix_backend.modules.coding.tools import FX_PROVIDERS, Codex, Fx, Usage


def test_a_turn_is_priced_by_its_fresh_cached_and_written_tokens() -> None:
    # gpt-5.5: $5 in, $0.50 cached, $30 out per million.
    assert cost_of("openai:gpt-5.5", input_tokens=30_000, cached_input_tokens=20_000, output_tokens=500) == 0.075
    # Haiku 5.5: $0.10 in, $0.01 read, $0.125 written, $0.50 out.
    assert cost_of("anthropic:claude-haiku-5-5", input_tokens=40_000, cached_input_tokens=20_000,
                   cache_write_tokens=10_000, output_tokens=1_000) == 0.00295


def test_a_model_without_a_price_gets_no_cost_and_settings_can_add_one() -> None:
    assert cost_of("openai:gpt-6.1-sol", input_tokens=1000, output_tokens=10) is None
    assert cost_of(None, input_tokens=1000, output_tokens=10) is None
    assert cost_of("openai:gpt-6.1-sol", input_tokens=1_000_000, output_tokens=0,
                   overrides={"openai:gpt-6.1-sol": [2, 0.2, 2, 8]}) == 2.0


def test_codex_and_fx_report_their_cached_tokens() -> None:
    codex = Usage()
    Codex().parse(json.dumps({"type": "turn.completed", "usage": {
        "input_tokens": 30_000, "cached_input_tokens": 20_000, "output_tokens": 500}}), codex)
    assert (codex.input_tokens, codex.cached_input_tokens, codex.output_tokens, codex.cost_usd) == (30_000, 20_000, 500, None)
    fx = Usage()
    Fx(FX_PROVIDERS["anthropic"]).parse(json.dumps({"type": "done", "stopReason": "end_turn", "usage": {
        "inputTokens": 10_000, "cacheReadTokens": 20_000, "cacheWriteTokens": 10_000, "outputTokens": 1_000}}), fx)
    assert (fx.input_tokens, fx.cached_input_tokens, fx.cache_write_tokens, fx.output_tokens) == (40_000, 20_000, 10_000, 1_000)
