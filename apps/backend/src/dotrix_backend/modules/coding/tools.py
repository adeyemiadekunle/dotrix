"""The coding tools we wrap, run headless: the command line, and their JSON events read into
what the run page shows (steps) and what the run used (tokens).

- Claude Code: `claude -p --bare --output-format stream-json --verbose`, the brief on stdin.
  Headless has no prompts, so the tools it may use are pre-allowed (`--permission-mode dontAsk`
  refuses the rest); the sandbox's policy is the boundary for what Bash can reach.
- Codex: `codex exec --json … -`, the brief on stdin, with Codex's own sandbox off
  (`danger-full-access`) because the run is already in one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from dotrix_backend.core.settings import Settings

from .models import CodingAgent

MAX_STEP = 300  # characters of one step shown on the run page
CLAUDE_TOOLS = "Read,Edit,Write,MultiEdit,Glob,Grep,Bash,TodoWrite"


@dataclass(frozen=True)
class Step:
    kind: str  # "text" (the agent's words), "tool" (what it did), "step", "error"
    text: str


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    # Claude Code repeats a model call's usage on each of its content blocks: counted once.
    _calls: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class Parsed:
    steps: list[Step] = field(default_factory=list)
    summary: str | None = None  # the agent's final message, when this line carried it
    failed: str | None = None  # the tool reported it couldn't finish


class CodingTool(Protocol):
    agent: CodingAgent
    key_env: str  # the model key's environment variable
    provider_type: str  # its OpenShell provider profile

    def command(self, model: str | None) -> list[str]: ...
    def parse(self, line: str, usage: Usage) -> Parsed: ...


def _clip(text: str, limit: int = MAX_STEP) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _relative(path: str) -> str:
    for prefix in ("/sandbox/repo/", "./"):
        if path.startswith(prefix):
            return path[len(prefix):]
    return path.rsplit("/repo/", 1)[-1] if "/repo/" in path else path


def _describe_claude_tool(name: str, args: dict[str, Any]) -> str | None:
    path = _relative(str(args.get("file_path") or args.get("path") or ""))
    match name:
        case "Bash":
            return f"Ran {_clip(str(args.get('command', '')), 160)}"
        case "Edit" | "MultiEdit":
            return f"Edited {path}"
        case "Write":
            return f"Wrote {path}"
        case "Read":
            return f"Read {path}"
        case "Glob" | "Grep":
            return f"Searched for {_clip(str(args.get('pattern', '')), 80)}"
        case "TodoWrite":
            return None
        case _:
            return f"Used {name}"


class ClaudeCode:
    agent = CodingAgent.CLAUDE_CODE
    key_env = "ANTHROPIC_API_KEY"
    provider_type = "dotrix-claude-code"

    def command(self, model: str | None) -> list[str]:
        argv = [
            "claude", "-p", "--bare", "--output-format", "stream-json", "--verbose",
            "--permission-mode", "dontAsk", "--allowedTools", CLAUDE_TOOLS,
            "--disallowedTools", "WebFetch,WebSearch",
        ]
        return argv + (["--model", model] if model else [])

    def parse(self, line: str, usage: Usage) -> Parsed:
        out = Parsed()
        event = _json(line)
        if event is None:
            return out
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            out.steps.append(Step("step", f"Claude Code started ({event.get('model') or 'default model'})"))
        elif kind == "system" and event.get("subtype") == "api_retry":
            error = str(event.get("error") or event.get("error_status") or "error")
            if event.get("error_status") in (401, 403):  # retrying won't help: stop now
                out.failed = f"The model provider refused the key ({error})"
            else:
                out.steps.append(Step("error", f"A model call failed ({error}); retry {event.get('attempt')}"))
        elif kind == "assistant":
            message = event.get("message") or {}
            for block in message.get("content") or []:
                if block.get("type") == "text" and block.get("text", "").strip():
                    out.steps.append(Step("text", _clip(block["text"])))
                elif block.get("type") == "tool_use":
                    said = _describe_claude_tool(str(block.get("name")), block.get("input") or {})
                    if said:
                        out.steps.append(Step("tool", said))
            calls = message.get("usage") or {}
            if message.get("id") and calls:
                usage._calls[message["id"]] = (
                    int(calls.get("input_tokens") or 0) + int(calls.get("cache_creation_input_tokens") or 0)
                    + int(calls.get("cache_read_input_tokens") or 0),
                    int(calls.get("output_tokens") or 0),
                )
                usage.input_tokens = sum(i for i, _ in usage._calls.values())
                usage.output_tokens = sum(o for _, o in usage._calls.values())
        elif kind == "result":
            totals = event.get("usage") or {}
            if totals:
                usage.input_tokens = max(usage.input_tokens, int(totals.get("input_tokens") or 0)
                                         + int(totals.get("cache_creation_input_tokens") or 0)
                                         + int(totals.get("cache_read_input_tokens") or 0))
                usage.output_tokens = max(usage.output_tokens, int(totals.get("output_tokens") or 0))
            if event.get("total_cost_usd") is not None:
                usage.cost_usd = float(event["total_cost_usd"])
            if event.get("is_error") or str(event.get("subtype", "")).startswith("error"):
                out.failed = _clip(str(event.get("result") or event.get("subtype") or "Claude Code stopped"), 500)
            elif event.get("result"):
                out.summary = str(event["result"])[:20_000]
        return out


class Codex:
    agent = CodingAgent.CODEX
    key_env = "OPENAI_API_KEY"
    provider_type = "dotrix-codex"

    def command(self, model: str | None) -> list[str]:
        argv = ["codex", "exec", "--json", "--skip-git-repo-check", "--sandbox", "danger-full-access", "--ephemeral"]
        return argv + (["-c", f'model="{model}"'] if model else []) + ["-"]

    def parse(self, line: str, usage: Usage) -> Parsed:
        out = Parsed()
        event = _json(line)
        if event is None:
            return out
        kind = event.get("type")
        item = event.get("item") or {}
        if kind == "thread.started":
            out.steps.append(Step("step", "Codex started"))
        elif kind == "item.started" and item.get("type") == "command_execution":
            out.steps.append(Step("tool", f"Ran {_clip(str(item.get('command', '')), 160)}"))
        elif kind == "item.completed":
            match item.get("type"):
                case "agent_message" if str(item.get("text", "")).strip():
                    out.steps.append(Step("text", _clip(item["text"])))
                    out.summary = str(item["text"])[:20_000]
                case "file_change":
                    for change in item.get("changes") or []:
                        out.steps.append(Step("tool", f"Edited {_relative(str(change.get('path', '')))}"))
        elif kind == "turn.completed":
            turn = event.get("usage") or {}
            usage.input_tokens += int(turn.get("input_tokens") or 0)
            usage.output_tokens += int(turn.get("output_tokens") or 0)
        elif kind in ("turn.failed", "error"):
            message = (event.get("error") or {}).get("message") if kind == "turn.failed" else event.get("message")
            out.failed = _clip(str(message or "Codex stopped"), 500)
        return out


def _json(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


TOOLS: dict[CodingAgent, CodingTool] = {CodingAgent.CLAUDE_CODE: ClaudeCode(), CodingAgent.CODEX: Codex()}


def model_key(settings: Settings, agent: CodingAgent) -> str | None:
    secret = settings.anthropic_api_key if agent is CodingAgent.CLAUDE_CODE else settings.openai_api_key
    return secret.get_secret_value() if secret is not None else None


def choose_agent(settings: Settings) -> CodingAgent | None:
    """Claude Code when the server has an Anthropic key, else Codex with an OpenAI key (or the one
    `DOTRIX_CODING_AGENT` names, if its key is there); None when neither can run."""
    if settings.coding_agent != "auto":
        agent = CodingAgent(settings.coding_agent)
        return agent if model_key(settings, agent) else None
    for agent in (CodingAgent.CLAUDE_CODE, CodingAgent.CODEX):
        if model_key(settings, agent):
            return agent
    return None


def model_for(settings: Settings, agent: CodingAgent) -> str | None:
    return settings.coding_claude_model if agent is CodingAgent.CLAUDE_CODE else settings.coding_codex_model
