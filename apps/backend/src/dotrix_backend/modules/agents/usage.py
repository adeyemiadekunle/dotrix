"""Token usage of an agent run, counted from every model call it makes (feeds FR-28 spend
limits, and shows when a model stopped early: an empty reply with zero output tokens).

Besides the totals, a run keeps a breakdown for owners and admins: tokens by agent (the PM
and each specialist) and by pipeline stage (`agent/stage`), what each tool returned (tool results are re-sent with every later
call, so a big result is paid for many times), and which files were read. And a budget: a
run stops before a model call once it has used its token budget.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from dotrix_engine.agent import role_for_agent_name

# Roughly four characters per token: good enough to rank tool results by size.
CHARS_PER_TOKEN = 4
# Tools whose `file_path` argument is a file being read.
READ_TOOLS = ("read_file", "read_section", "document_outline")
MAX_FILES_LISTED = 50


class TokenBudgetExceeded(Exception):  # noqa: N818 - reads better where it's caught
    def __init__(self, used: int, budget: int) -> None:
        super().__init__(f"Token budget reached: {used:,} of {budget:,} tokens used")
        self.used, self.budget = used, budget


def _approx_tokens(value: Any) -> int:
    content = getattr(value, "content", value)
    return len(content if isinstance(content, str) else str(content)) // CHARS_PER_TOKEN


def _agent(metadata: dict[str, Any] | None) -> str:
    return role_for_agent_name((metadata or {}).get("lc_agent_name"))


class TokenUsage(BaseCallbackHandler):
    """Adds up the input and output tokens of every model call it sees.

    Given in a graph's config (`callbacks`), it's inherited by child runs, so tool calls and
    the subagents the `task` tool starts are counted too. Unlike langchain's
    `UsageMetadataCallbackHandler`, it counts calls whose response has no model name (the
    scripted test models) and keeps one total rather than one per model.

    `on_llm_end` gets the whole message even when the model streams, so chunks aren't counted
    twice.

    `budget` is the run's limit in tokens (input + output, every step of the run); `used`
    what earlier steps already spent. Past the budget, the next model call raises
    TokenBudgetExceeded (`raise_error`), which ends the step.
    """

    run_inline = True
    raise_error = True

    def __init__(self, *, budget: int | None = None, used: int = 0, stages: dict[str, str] | None = None) -> None:
        super().__init__()
        self.budget = budget or None
        self.used_before = used
        self.stages = dict(stages or {})
        # The step's web use (dotrix_engine.web.WebUsage: run totals, seeded from earlier steps).
        self.web: Any = None
        self._reset()

    def _reset(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        # Input tokens the provider served from its prompt cache (billed at a fraction): the
        # part of each prompt that repeats, like the instructions and the context pack.
        self.cached_input_tokens = 0
        # Each call re-sends the whole prompt, so fewer steps is the other big saving.
        self.model_calls = 0
        self.by_agent: dict[str, dict[str, int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "model_calls": 0}
        )
        # Keyed "agent/stage": the calls each agent made while in a pipeline stage.
        self.by_stage: dict[str, dict[str, int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "model_calls": 0}
        )
        self.tools: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "result_tokens": 0})
        self.files_read: dict[str, int] = defaultdict(int)
        self._agents: dict[UUID, str] = {}
        self._tool_names: dict[UUID, str] = {}

    # The stage each agent is in, from its `stage` calls (kept across steps of a run).
    stages: dict[str, str]

    def enter_stage(self, agent: str, stage: str) -> None:
        self.stages[agent] = stage

    @property
    def used(self) -> int:
        return self.used_before + self.input_tokens + self.output_tokens

    # -- model calls -------------------------------------------------------------------

    def _started(self, run_id: UUID, metadata: dict[str, Any] | None) -> None:
        if self.budget is not None and self.used >= self.budget:
            raise TokenBudgetExceeded(self.used, self.budget)
        self._agents[run_id] = _agent(metadata)

    def on_chat_model_start(
        self, serialized: dict[str, Any], messages: Any, *, run_id: UUID, metadata: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        self._started(run_id, metadata)

    def on_llm_start(
        self, serialized: dict[str, Any], prompts: list[str], *, run_id: UUID, metadata: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        self._started(run_id, metadata)

    def on_llm_end(self, response: LLMResult, *, run_id: UUID | None = None, **kwargs: Any) -> None:
        self.model_calls += 1
        name = (self._agents.pop(run_id, None) or role_for_agent_name(None)) if run_id else None
        counters = []
        if name is not None:
            counters.append(self.by_agent[name])
            if name in self.stages:
                counters.append(self.by_stage[f"{name}/{self.stages[name]}"])
        for counter in counters:
            counter["model_calls"] += 1
        for generations in response.generations:
            for generation in generations:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None)
                if usage:
                    input_tokens = int(usage.get("input_tokens") or 0)
                    output_tokens = int(usage.get("output_tokens") or 0)
                    self.input_tokens += input_tokens
                    self.output_tokens += output_tokens
                    details = usage.get("input_token_details") or {}
                    self.cached_input_tokens += int(details.get("cache_read") or 0)
                    for counter in counters:
                        counter["input_tokens"] += input_tokens
                        counter["output_tokens"] += output_tokens

    # -- tools -------------------------------------------------------------------------

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        name = str((serialized or {}).get("name") or kwargs.get("name") or "tool")
        self._tool_names[run_id] = name
        self.tools[name]["calls"] += 1
        path = (inputs or {}).get("file_path") if isinstance(inputs, dict) else None
        if name in READ_TOOLS and isinstance(path, str):
            self.files_read[path] += 1

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        if (name := self._tool_names.pop(run_id, None)) is not None:
            self.tools[name]["result_tokens"] += _approx_tokens(output)

    # -- reporting ---------------------------------------------------------------------

    def details(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "model_calls": self.model_calls,
        }

    def breakdown(self) -> dict[str, Any]:
        """This step's breakdown, in the shape stored on the run (`merge_breakdown`)."""
        return {
            "by_agent": {name: dict(counts) for name, counts in self.by_agent.items()},
            "by_stage": {name: dict(counts) for name, counts in self.by_stage.items()},
            "tools": {name: dict(counts) for name, counts in self.tools.items()},
            "files_read": dict(self.files_read),
            "stages": dict(self.stages),
            **({"web": {"searches": self.web.searches, "fetches": self.web.fetches, "credits": self.web.credits,
                        "flagged": list(self.web.flagged)}} if self.web is not None else {}),
        }

    def take(self) -> tuple[dict[str, int], dict[str, Any]]:
        """The totals and the breakdown so far, starting again from zero, so what's already
        recorded on the run isn't added twice."""
        details, breakdown = self.details(), self.breakdown()
        self.used_before += self.input_tokens + self.output_tokens
        self._reset()
        return details, breakdown


def merge_breakdown(stored: dict[str, Any] | None, step: dict[str, Any]) -> dict[str, Any]:
    """A run's breakdown with one more step's added (runs resume after approvals)."""
    merged: dict[str, Any] = {"by_agent": {}, "by_stage": {}, "tools": {}, "files_read": {}}
    for part in ("by_agent", "by_stage", "tools"):
        for source in ((stored or {}).get(part) or {}, step.get(part) or {}):
            for name, counts in source.items():
                into = merged[part].setdefault(name, {})
                for key, value in counts.items():
                    into[key] = into.get(key, 0) + int(value)
    for source in ((stored or {}).get("files_read") or {}, step.get("files_read") or {}):
        for path, times in source.items():
            merged["files_read"][path] = merged["files_read"].get(path, 0) + int(times)
    # Where each agent is now: the latest step's word wins.
    merged["stages"] = {**((stored or {}).get("stages") or {}), **(step.get("stages") or {})}
    # Web use is kept as run totals (each step starts from the last), so the latest wins.
    if web := step.get("web") or (stored or {}).get("web"):
        merged["web"] = web
    if len(merged["files_read"]) > MAX_FILES_LISTED:
        top = sorted(merged["files_read"].items(), key=lambda item: -item[1])[:MAX_FILES_LISTED]
        merged["files_read"] = dict(top)
    return merged
