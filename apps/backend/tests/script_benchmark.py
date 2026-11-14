"""Test-only Code Mode measurements. Never retain tool content, prompts or credentials."""
from __future__ import annotations

import contextvars
import dataclasses
import json
from collections.abc import Mapping
from typing import Any

from dotrix_backend.modules.agents import scripts
from dotrix_backend.modules.agents.usage import TokenUsage
from dotrix_engine.runtimes.fx import FxRuntime


def result_bytes(value: Any) -> int:
    """UTF-8 content/JSON bytes, not provider tokens or HTTP wire bytes."""
    value = getattr(value, "content", value)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return len(text.encode("utf-8"))


@dataclasses.dataclass
class Measurements:
    script_invocations: int = 0
    script_read_calls: int = 0
    script_read_result_bytes: int = 0
    model_visible_result_bytes: int = 0
    model_visible_results: int = 0

    def visible(self, value: Any) -> None:
        self.model_visible_results += 1
        self.model_visible_result_bytes += result_bytes(value)


def instrument(monkeypatch: Any) -> Measurements:
    """Observe successful tool results at each runtime boundary; retain normal execution/checks.

    DeepAgents nested tools inside run_script do not reach the model separately. fx sends
    only outer results over its tool_reply bridge. Neither count includes repeated history,
    provider formatting, errors, or any filtering subsequently applied by the runtime.
    """
    measured = Measurements()
    inside = contextvars.ContextVar("benchmark_inside_script", default=False)
    original_script = scripts.run_script
    original_end = TokenUsage.on_tool_end
    original_send = FxRuntime._send

    async def run(code: str, functions: Mapping[str, scripts.ScriptFunctionSpec], *, on_call=None) -> str:
        measured.script_invocations += 1

        def observe(spec):
            async def call(args):
                result = await spec.call(args)
                measured.script_read_calls += 1
                measured.script_read_result_bytes += result_bytes(result)
                return result
            return dataclasses.replace(spec, call=call)

        token = inside.set(True)
        try:
            return await original_script(code, {name: observe(spec) for name, spec in functions.items()}, on_call=on_call)
        finally:
            inside.reset(token)

    def ended(self, output, *, run_id, **kwargs):
        if not inside.get() and getattr(output, "status", None) != "error":
            measured.visible(output)
        return original_end(self, output, run_id=run_id, **kwargs)

    async def sent(self, payload):
        result = await original_send(self, payload)
        if payload.get("op") == "tool_reply" and payload.get("ok") and "result" in payload:
            measured.visible(payload["result"])
        return result

    monkeypatch.setattr(scripts, "run_script", run)
    monkeypatch.setattr(TokenUsage, "on_tool_end", ended)
    monkeypatch.setattr(FxRuntime, "_send", sent)
    return measured
